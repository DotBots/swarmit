"""Module for the web server application."""

import asyncio
import base64
import datetime
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import List, Optional, Union

import jwt
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi import status as fastapi_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swarmit import __version__
from swarmit.testbed.controller import (
    Controller,
    ControllerSettings,
    ResetLocation,
)
from swarmit.testbed.model import (
    Base,
    JWTRecord,
    create_db_engine,
    create_prevent_overlap_trigger,
    create_session_factory,
)
from swarmit.testbed.protocol import StatusType

DATA_DIR = "./.data"
API_DB_URL = f"sqlite:///{DATA_DIR}/database.db"


def get_db():
    global SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


api = FastAPI(
    debug=0,
    title="SwarmIT Dashboard API",
    description="This is the SwarmIT Dashboard API",
    version=__version__,
    docs_url="/api",
    redoc_url=None,
)
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global lock to prevent concurrent controller access
controller_lock = asyncio.Lock()


# Load Ed25519 keys
def get_private_key() -> str:
    with open(f"{DATA_DIR}/private.pem") as f:
        return f.read()


def get_public_key() -> str:
    with open(f"{DATA_DIR}/public.pem") as f:
        return f.read()


ALGORITHM = "EdDSA"
security = HTTPBearer()


def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        public_key = get_public_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="public.pem not found; public key unavailable",
        )
    try:
        payload = jwt.decode(
            credentials.credentials, public_key, algorithms=[ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def init_api(api: FastAPI, settings: ControllerSettings):
    controller = Controller(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global SessionLocal
        engine = create_db_engine(API_DB_URL)
        SessionLocal = create_session_factory(engine)
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            create_prevent_overlap_trigger(conn)

        await controller.setup()
        app.state.controller = controller
        app.state.ota_transfer_status = "idle"
        app.state.ota_transfer_error = None

        yield

        await controller.terminate()
        engine.dispose()

    api.router.lifespan_context = lifespan
    return controller


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------


class DeviceList(BaseModel):
    devices: Optional[Union[str, List[str]]] = None

    @field_validator("devices", mode="before")
    def validate_devices(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            if not all(isinstance(item, str) for item in v):
                raise ValueError("devices must be a list of strings")
            return v
        raise ValueError("devices must be a string or list of strings")


class OtaStartRequest(BaseModel):
    firmware_b64: str
    devices: Optional[Union[str, List[str]]] = None

    @field_validator("devices", mode="before")
    def validate_devices(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            if not all(isinstance(item, str) for item in v):
                raise ValueError("devices must be a list of strings")
            return v
        raise ValueError("devices must be a string or list of strings")


class OtaTransferRequest(BaseModel):
    devices: List[str]


class ResetRequest(BaseModel):
    locations: dict  # addr_str -> {"pos_x": int, "pos_y": int}


class MessageRequest(BaseModel):
    message: str
    devices: Optional[Union[str, List[str]]] = None

    @field_validator("devices", mode="before")
    def validate_devices(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            if not all(isinstance(item, str) for item in v):
                raise ValueError("devices must be a list of strings")
            return v
        raise ValueError("devices must be a string or list of strings")


# ------------------------------------------------------------------
# OTA background tasks
# ------------------------------------------------------------------


async def _start_ota_background(
    app: FastAPI, fw: bytearray, devices: list[str]
):
    """Negotiate OTA start with devices in a background task."""
    controller: Controller = app.state.controller
    async with controller_lock:
        await controller.start_ota(fw, devices if devices else None)


async def _transfer_background(app: FastAPI, devices: list[str]):
    """Transfer OTA chunks to *devices* in a background task."""
    controller: Controller = app.state.controller
    try:
        async with controller_lock:
            data = await controller.transfer(devices)
        if all(d.success for d in data.values()):
            app.state.ota_transfer_status = "success"
            app.state.ota_transfer_error = None
        else:
            app.state.ota_transfer_status = "failed"
            app.state.ota_transfer_error = "transfer failed"
    except Exception as exc:
        app.state.ota_transfer_status = "failed"
        app.state.ota_transfer_error = str(exc)


# ------------------------------------------------------------------
# OTA endpoints
# ------------------------------------------------------------------


@api.post("/ota/start", dependencies=[Depends(verify_jwt)])
async def ota_start(
    payload: OtaStartRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Initiate OTA start negotiation with devices (non-blocking).

    Returns immediately.  Poll ``GET /ota/start/status`` to know when
    all devices have acknowledged and which ones missed the deadline.
    """
    controller: Controller = request.app.state.controller

    try:
        fw = bytearray(base64.b64decode(payload.firmware_b64))
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid firmware encoding: {exc}"
        )

    devices = payload.devices
    if devices:
        ready = [
            d
            for d in devices
            if d in controller.status_data
            and controller.status_data[d].status == StatusType.Bootloader
        ]
        if not ready:
            raise HTTPException(
                status_code=400, detail="no ready devices to flash"
            )
    else:
        if not controller.ready_devices:
            raise HTTPException(
                status_code=400, detail="no ready devices to flash"
            )

    # Reset start data to "pending" before spawning the background task so
    # that /ota/start/status immediately reflects the in-progress state.
    controller.start_ota_data.status = "pending"
    controller.start_ota_data.acked = []
    controller.start_ota_data.missed = []
    background_tasks.add_task(
        _start_ota_background, request.app, fw, devices or []
    )
    return JSONResponse(content={"status": "pending"})


@api.get("/ota/start/status", dependencies=[Depends(verify_jwt)])
async def ota_start_status(request: Request):
    """Return the current OTA start negotiation status.

    Poll until ``status`` is ``"done"``, then inspect ``acked`` and
    ``missed`` before calling ``POST /ota/transfer``.
    """
    controller: Controller = request.app.state.controller
    d = controller.start_ota_data
    return JSONResponse(
        content={
            "status": d.status,
            "acked": d.acked,
            "missed": d.missed,
            "total_chunks": d.chunks,
            "fw_hash": d.fw_hash.hex().upper() if d.fw_hash else "",
        }
    )


@api.post("/ota/transfer", dependencies=[Depends(verify_jwt)])
async def ota_transfer(
    payload: OtaTransferRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Start the OTA chunk transfer in the background.

    ``POST /ota/start`` must have completed (``/ota/start/status`` returns
    ``"done"``) before calling this endpoint.  Poll
    ``GET /ota/transfer/status`` to track completion.
    """
    if request.app.state.ota_transfer_status == "running":
        raise HTTPException(
            status_code=409, detail="OTA transfer already in progress"
        )

    request.app.state.ota_transfer_status = "running"
    request.app.state.ota_transfer_error = None
    background_tasks.add_task(
        _transfer_background, request.app, payload.devices
    )
    return JSONResponse(content={"status": "started"})


@api.get("/ota/transfer/status", dependencies=[Depends(verify_jwt)])
async def ota_transfer_status(request: Request):
    """Return the current OTA chunk transfer progress."""
    controller: Controller = request.app.state.controller
    total_chunks = controller.start_ota_data.chunks
    devices_progress = {
        addr: {
            "chunks_acked": sum(1 for c in status.chunks if c.acked),
            "total_chunks": total_chunks,
            "success": status.success,
        }
        for addr, status in controller.transfer_data.items()
    }
    return JSONResponse(
        content={
            "status": request.app.state.ota_transfer_status,
            "error": request.app.state.ota_transfer_error,
            "total_chunks": total_chunks,
            "devices": devices_progress,
        }
    )


# ------------------------------------------------------------------
# Device status / settings
# ------------------------------------------------------------------


@api.get("/status")
async def status(request: Request):
    controller: Controller = request.app.state.controller
    response = {
        k: {
            **asdict(v),
            "device": v.device.name,
            "status": v.status.name,
        }
        for k, v in controller.status_data.items()
    }
    return JSONResponse(content={"response": response})


class SettingsResponse(BaseModel):
    network_id: int
    area_width: int
    area_height: int


@api.get("/settings", response_model=SettingsResponse)
async def settings(request: Request):
    controller: Controller = request.app.state.controller
    map_size = controller.settings.map_size
    width_str, height_str = map_size.lower().split("x")
    return SettingsResponse(
        network_id=controller.settings.network_id,
        area_width=int(width_str),
        area_height=int(height_str),
    )


# ------------------------------------------------------------------
# Command endpoints
# ------------------------------------------------------------------


@api.post("/start")
async def start(
    request: Request,
    payload: DeviceList,
    _token_payload=Depends(verify_jwt),
):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await controller.start(devices=payload.devices)
    return JSONResponse(content={"response": "done"})


@api.post("/stop", dependencies=[Depends(verify_jwt)])
async def stop(request: Request, payload: DeviceList):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await controller.stop(devices=payload.devices)
    return JSONResponse(content={"response": "done"})


@api.post("/reset", dependencies=[Depends(verify_jwt)])
async def reset(request: Request, payload: ResetRequest):
    controller: Controller = request.app.state.controller
    try:
        locations = {
            addr: ResetLocation(
                pos_x=int(loc["pos_x"]),
                pos_y=int(loc["pos_y"]),
            )
            for addr, loc in payload.locations.items()
        }
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid location data: {exc}"
        )
    async with controller_lock:
        await controller.reset(locations)
    return JSONResponse(content={"response": "done"})


@api.post("/message", dependencies=[Depends(verify_jwt)])
async def message(request: Request, payload: MessageRequest):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await controller.send_message(payload.message, payload.devices)
    return JSONResponse(content={"response": "done"})


# ------------------------------------------------------------------
# JWT management
# ------------------------------------------------------------------


class IssueRequest(BaseModel):
    start: str  # ISO8601 string


@api.post("/issue_jwt")
def issue_token(req: IssueRequest, db: Session = Depends(get_db)):
    try:
        start = datetime.datetime.fromisoformat(
            req.start.replace("Z", "+00:00")
        )
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid 'start' time format (use ISO8601)"
        )

    end = start + datetime.timedelta(minutes=30)
    payload = {
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "nbf": start,
        "exp": end,
    }

    try:
        private_key = get_private_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="private.pem not found; private key unavailable",
        )
    token = jwt.encode(payload, private_key, algorithm=ALGORITHM)

    db_record = JWTRecord(jwt=token, date_start=start, date_end=end)
    db.add(db_record)
    try:
        db.commit()
        db.refresh(db_record)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Timeslot already full")

    return {"data": token}


@api.get("/public_key")
def public_key():
    """Expose the public key (frontend can use this to verify JWT signatures)."""
    try:
        key = get_public_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="public.pem not found; public key unavailable",
        )
    return JSONResponse(content={"data": key})


class JWTRecordOut(BaseModel):
    date_start: datetime.datetime
    date_end: datetime.datetime

    model_config = {"from_attributes": True}


@api.get("/records", response_model=list[JWTRecordOut])
def list_records(db: Session = Depends(get_db)):
    now = datetime.datetime.now(datetime.timezone.utc)
    yesterday = now - datetime.timedelta(days=1)
    one_month_later = now + datetime.timedelta(days=30)
    records = (
        db.query(JWTRecord)
        .filter(
            JWTRecord.date_start >= yesterday,
            JWTRecord.date_start <= one_month_later,
        )
        .order_by(asc(JWTRecord.date_start))
        .all()
    )
    return records


# ------------------------------------------------------------------
# Static frontend
# ------------------------------------------------------------------


def mount_frontend(api):
    dashboard_dir = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "frontend", "build"
    )
    if os.path.isdir(dashboard_dir):
        api.mount(
            "/",
            StaticFiles(directory=dashboard_dir, html=True),
            name="dashboard",
        )
    else:
        print("Warning: dashboard directory not found; skipping static mount")
