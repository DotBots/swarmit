"""Module for the web server application."""

import asyncio
import base64
import datetime
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Dict, List, Optional, Union

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
from fastapi.responses import JSONResponse, StreamingResponse
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

# Serializes every write operation that touches the Controller's state
# machine. All POST endpoints (/flash, /flash/stream, /start, /stop,
# /reset, /message, /lh2_calibration) acquire this. Held for the FULL
# duration of /flash/stream — minutes for a large image — which means
# every other write endpoint blocks during a flash. This is intentional:
# only one OTA at a time, and concurrent start/stop during a flash would
# fight the controller's per-bot state. Reads (/status, /settings,
# /events) do NOT take the lock.
controller_lock = asyncio.Lock()


# Load Ed25519 keys
def get_private_key() -> str:
    with open(f"{DATA_DIR}/private.pem") as f:
        return f.read()


def get_public_key() -> str:
    with open(f"{DATA_DIR}/public.pem") as f:
        return f.read()


ALGORITHM = "EdDSA"
security = HTTPBearer(auto_error=False)

# Module-level auth toggle. The dashboard (init_api with default auth_mode)
# leaves this True. The daemon (auth_mode="none") flips it to False, which
# makes verify_jwt a no-op and skips DB initialization (JWT records DB).
AUTH_ENABLED = True


def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not AUTH_ENABLED:
        return None
    if credentials is None:
        raise HTTPException(
            status_code=fastapi_status.HTTP_403_FORBIDDEN,
            detail="Not authenticated",
        )
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


def init_api(
    api: FastAPI,
    settings: ControllerSettings,
    auth_mode: str = "jwt",
):
    """Wire up the FastAPI app with a Controller and a lifespan.

    auth_mode:
      - "jwt" (default): JWT auth on write endpoints; JWT records DB enabled.
        Used by the dashboard.
      - "none": auth disabled (verify_jwt no-ops); DB not initialized.
        Used by the daemon when bound to localhost.
    """
    global AUTH_ENABLED
    AUTH_ENABLED = auth_mode != "none"
    db_enabled = auth_mode != "none"

    controller = Controller(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        if db_enabled:
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
        if engine is not None:
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
    # Per-flash overrides. None = use the daemon's controller defaults.
    ota_timeout: Optional[float] = None
    ota_max_retries: Optional[int] = None


class MessageRequest(BaseModel):
    message: str


class ResetLocationModel(BaseModel):
    pos_x: int
    pos_y: int


class ResetRequest(BaseModel):
    """Reset robot locations.

    `locations` maps hex device address (e.g. "BC3D3C8A2A6F8E68") to its new
    (pos_x, pos_y). The keys must match `settings.devices`; mismatch is a 400.
    """

    locations: Dict[str, ResetLocationModel]


class Lh2CalibrationRequest(BaseModel):
    """Send LH2 calibration data to the swarm.

    `calibration_b64` is the base64-encoded blob in the format expected by
    Controller.send_lh2_calibration: 1-byte count followed by N × 36-byte
    homography matrices (3×3 int32_t each).
    """

    calibration_b64: str


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


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@api.post("/flash/stream", dependencies=[Depends(verify_jwt)])
async def flash_stream(payload: FlashRequest, request: Request):
    """OTA flash with progress streamed back as Server-Sent Events.

    Event types yielded in order:
      - "flash_started":     {image_size, total_chunks, fw_hash, devices}
      - "chunk" (repeated):  {addr, acked, total}   — cumulative acked count
      - "device_done" (per): {addr, success, retries}
      - "complete":          {all_success, elapsed_s}
      - "error" (terminal):  {message}
    """
    controller: Controller = request.app.state.controller

    try:
        fw = bytearray(base64.b64decode(payload.firmware_b64))
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"invalid firmware encoding: {e}"
        )

    devices = payload.devices

    async def event_stream():
        async with controller_lock:
            # Per-flash override of OTA params: save the controller's
            # current values, apply the request's overrides (if any),
            # restore on exit. Safe under controller_lock — no other
            # flash can interleave.
            saved_timeout = controller.settings.ota_timeout
            saved_retries = controller.settings.ota_max_retries
            if payload.ota_timeout is not None:
                controller.settings.ota_timeout = payload.ota_timeout
            if payload.ota_max_retries is not None:
                controller.settings.ota_max_retries = payload.ota_max_retries
            try:
                async for ev in _do_flash(controller, fw, devices):
                    yield ev
            finally:
                controller.settings.ota_timeout = saved_timeout
                controller.settings.ota_max_retries = saved_retries

    async def _do_flash(controller, fw, devices):
        try:
            start_data = (
                await run_in_threadpool(controller.start_ota, fw, devices)
                if devices
                else await run_in_threadpool(controller.start_ota, fw)
            )
        except Exception as exc:
            yield _sse({"type": "error", "message": f"start_ota: {exc}"})
            return

        if start_data["missed"]:
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        f"{len(start_data['missed'])} OTA start acks "
                        f"missed: {sorted(set(start_data['missed']))}"
                    ),
                }
            )
            return

        yield _sse(
            {
                "type": "flash_started",
                "image_size": len(fw),
                "total_chunks": len(controller.chunks),
                "fw_hash": start_data["ota"].fw_hash.hex().upper(),
                "devices": sorted(start_data["acked"]),
            }
        )

        transfer_task = asyncio.create_task(
            run_in_threadpool(
                controller.transfer,
                fw,
                start_data["acked"],
                False,  # show_progress=False — we stream events instead
            )
        )

        last_acked = {addr: 0 for addr in start_data["acked"]}
        start_ts = asyncio.get_running_loop().time()
        # If the HTTP client disconnects mid-flash, this async generator
        # gets a CancelledError, but the threadpool transfer keeps
        # running to completion. Intentional: aborting an in-flight OTA
        # leaves devices in an unknown half-flashed state, which is
        # worse than just letting the OTA finish and dropping the
        # progress stream.
        while not transfer_task.done():
            await asyncio.sleep(0.1)
            for addr in start_data["acked"]:
                td = controller.transfer_data.get(addr)
                if td is None:
                    continue
                acked = sum(1 for c in td.chunks if c.acked)
                if acked > last_acked[addr]:
                    yield _sse(
                        {
                            "type": "chunk",
                            "addr": addr,
                            "acked": acked,
                            "total": len(td.chunks),
                        }
                    )
                    last_acked[addr] = acked

        try:
            transfer = await transfer_task
        except Exception as exc:
            yield _sse({"type": "error", "message": f"transfer: {exc}"})
            return

        for addr, td in transfer.items():
            yield _sse(
                {
                    "type": "device_done",
                    "addr": addr,
                    "success": td.success,
                    "retries": sum(c.retries for c in td.chunks),
                    "chunks_acked": sum(1 for c in td.chunks if c.acked),
                    "chunks_total": len(td.chunks),
                }
            )

        yield _sse(
            {
                "type": "complete",
                "all_success": all(td.success for td in transfer.values()),
                "elapsed_s": asyncio.get_running_loop().time() - start_ts,
            }
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    calibration_distance: int  # mm; the -d value used by dotbot-calibration


@api.get("/settings", response_model=SettingsResponse)
async def settings(request: Request):
    controller: Controller = request.app.state.controller
    map_size = controller.settings.map_size
    width_str, height_str = map_size.lower().split('x')
    width, height = int(width_str), int(height_str)
    # If the operator didn't pass --calibration-distance explicitly, infer it
    # from the arena: single-LH calibration produces a 5d × 5d arena, so
    # d = min(w, h) / 5. For multi-LH arenas where the arena extends beyond
    # the first LH's coverage, the operator must pass the real value.
    cd = controller.settings.calibration_distance or (min(width, height) // 5)
    return SettingsResponse(
        network_id=controller.settings.network_id,
        area_width=width,
        area_height=height,
        calibration_distance=cd,
    )


@api.post("/start", dependencies=[Depends(verify_jwt)])
async def start(
    request: Request,
    payload: Optional[DeviceList] = None,
):
    controller: Controller = request.app.state.controller
    devices = payload.devices if payload is not None else None
    async with controller_lock:
        await run_in_threadpool(controller.start, devices=devices)

    return JSONResponse(content={"response": "done"})


@api.post("/stop", dependencies=[Depends(verify_jwt)])
async def stop(
    request: Request,
    payload: Optional[DeviceList] = None,
):
    controller: Controller = request.app.state.controller
    devices = payload.devices if payload is not None else None
    async with controller_lock:
        await run_in_threadpool(controller.stop, devices=devices)

    return JSONResponse(content={"response": "done"})


@api.post("/message", dependencies=[Depends(verify_jwt)])
async def message(request: Request, payload: MessageRequest):
    controller: Controller = request.app.state.controller
    async with controller_lock:
        await run_in_threadpool(controller.send_message, payload.message)
    return JSONResponse(content={"response": "done"})


@api.post("/reset", dependencies=[Depends(verify_jwt)])
async def reset(request: Request, payload: ResetRequest):
    controller: Controller = request.app.state.controller
    if not payload.locations:
        raise HTTPException(status_code=400, detail="no locations provided")

    # Controller.reset iterates over controller.settings.devices and indexes
    # the supplied locations dict by hex-string address. Build the dict in
    # that shape; the existing CLI's int-keyed dict is a separate bug.
    locations = {
        addr.upper(): ResetLocation(pos_x=loc.pos_x, pos_y=loc.pos_y)
        for addr, loc in payload.locations.items()
    }
    async with controller_lock:
        await run_in_threadpool(controller.reset, locations)
    return JSONResponse(content={"response": "done"})


@api.post("/lh2_calibration", dependencies=[Depends(verify_jwt)])
async def lh2_calibration(request: Request, payload: Lh2CalibrationRequest):
    controller: Controller = request.app.state.controller
    try:
        blob = base64.b64decode(payload.calibration_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid base64: {exc}")
    async with controller_lock:
        try:
            await run_in_threadpool(
                controller.send_lh2_calibration, bytearray(blob)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(content={"response": "done"})


@api.get("/events")
async def events(request: Request):
    """Server-Sent Events multiplex.

    Emits two event types over a single connection:
      - "status":    periodic device-state snapshot (every ~500 ms).
      - "log_event": pushed as soon as a SWARMIT_EVENT_LOG arrives.

    Disconnect cleanly via the underlying TCP close — the generator
    detects it via `request.is_disconnected()` and unregisters its
    log listener on exit.
    """
    controller: Controller = request.app.state.controller

    async def _snapshot() -> dict:
        # Snapshot first: status_data is mutated from the marilib RX
        # thread; iterating it directly across the sleep below would
        # race ("dictionary changed size during iteration").
        snapshot = dict(controller.status_data)
        return {
            addr: {
                **asdict(node),
                "device": node.device.name,
                "status": node.status.name,
            }
            for addr, node in snapshot.items()
        }

    async def event_generator():
        log_q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_log(event: dict) -> None:
            # Called from the controller's marilib RX thread; bridge to
            # the asyncio loop via call_soon_threadsafe.
            loop.call_soon_threadsafe(log_q.put_nowait, event)

        controller.add_log_event_listener(on_log)

        STATUS_INTERVAL = 0.5
        TICK = 0.05
        last_status = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    break

                # Drain any queued log events first so latency stays low.
                while not log_q.empty():
                    ev = log_q.get_nowait()
                    yield _sse({"type": "log_event", **ev})

                # Emit a status snapshot on its cadence.
                now = loop.time()
                if now - last_status >= STATUS_INTERVAL:
                    yield _sse(
                        {"type": "status", "devices": await _snapshot()}
                    )
                    last_status = now

                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            return
        finally:
            controller.remove_log_event_listener(on_log)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


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
