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
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi import status as fastapi_status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy import asc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swarmit import __version__
from swarmit.testbed.controller import Controller, ControllerSettings
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
        # Create engine + session factory
        engine = create_db_engine(API_DB_URL)
        SessionLocal = create_session_factory(engine)

        # Initialize DB schema
        Base.metadata.create_all(bind=engine)

        # Create triggers
        with engine.connect() as conn:
            create_prevent_overlap_trigger(conn)

        # Run on startup
        app.state.controller = controller

        yield

        # Run on shutdown
        controller.terminate()
        engine.dispose()

    api.router.lifespan_context = lifespan

    return controller


class DeviceList(BaseModel):
    devices: Optional[Union[str, List[str]]] = None

    @field_validator("devices", mode="before")
    def validate_devices(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            # ensure list of strings
            if not all(isinstance(item, str) for item in v):
                raise ValueError("devices must be a list of strings")
            return v
        raise ValueError("devices must be a string or list of strings")


class FlashRequest(BaseModel):
    firmware_b64: str
    devices: Optional[Union[str, List[str]]] = None


@api.post("/flash", dependencies=[Depends(verify_jwt)])
async def flash_firmware(payload: FlashRequest, request: Request):
    controller: Controller = request.app.state.controller

    try:
        fw_bytes = base64.b64decode(payload.firmware_b64)
        fw = bytearray(fw_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"invalid firmware encoding: {e}"
        )

    # Normalize devices
    devices = payload.devices
    if all(
        controller.status_data[device].status != StatusType.Bootloader
        for device in devices
    ):
        raise HTTPException(
            status_code=400, detail="no ready devices to flash"
        )

    async with controller_lock:

        start_data = (
            await run_in_threadpool(controller.start_ota, fw, devices)
            if devices
            else await run_in_threadpool(controller.start_ota, fw)
        )

        if start_data["missed"]:
            raise HTTPException(
                status_code=400,
                detail=f"{len(start_data['missed'])} acknowledgments are missing "
                f"({', '.join(sorted(set(start_data['missed'])))})",
            )

        data = await run_in_threadpool(
            controller.transfer, fw, start_data["acked"]
        )

    if all(device.success for device in data.values()) is False:
        raise HTTPException(status_code=400, detail="transfer failed")

    return JSONResponse(content={"response": "success"})


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
    width_str, height_str = map_size.lower().split('x')
    return SettingsResponse(
        network_id=controller.settings.network_id,
        area_width=int(width_str),
        area_height=int(height_str),
    )


@api.post("/start")
async def start(
    request: Request, payload: DeviceList, _token_payload=Depends(verify_jwt)
):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await run_in_threadpool(controller.start, devices=payload.devices)

    return JSONResponse(content={"response": "done"})


@api.post("/stop", dependencies=[Depends(verify_jwt)])
async def stop(request: Request, payload: DeviceList):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await run_in_threadpool(controller.stop, devices=payload.devices)

    return JSONResponse(content={"response": "done"})


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
        public_key = get_public_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="public.pem not found; public key unavailable",
        )

    return JSONResponse(content={"data": public_key})


class JWTRecordOut(BaseModel):
    date_start: datetime.datetime
    date_end: datetime.datetime

    model_config = {
        "from_attributes": True  # Enable Pydantic conversion from ORM objects
    }


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


# Mount static files after all routes are defined
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
