# SPDX-FileCopyrightText: 2022-present Inria
# SPDX-FileCopyrightText: 2022-present Alexandre Abadie <alexandre.abadie@inria.fr>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Module for the web server application."""

import base64
import datetime
import os
from dataclasses import asdict
from typing import List
import jwt
from pydantic import BaseModel

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from sqlalchemy import asc
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from dotbot import pydotbot_version

from testbed.swarmit.controller import Controller, ControllerSettings
from testbed.swarmit.model import JWTRecord, get_db

api = FastAPI(
    debug=0,
    title="DotBot controller API",
    description="This is the DotBot controller API",
    version=pydotbot_version(),
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

# Load RSA keys
with open("private.pem", "r") as f:
    PRIVATE_KEY = f.read()

with open("public.pem", "r") as f:
    PUBLIC_KEY = f.read()

ALGORITHM = "RS256"
security = HTTPBearer()

def verify_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, PUBLIC_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def init_api(api: FastAPI, settings: ControllerSettings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Run on startup 
        controller: Controller = Controller(settings)
        app.state.controller = controller

        yield
        
        # Run on shutdown 
        controller.terminate()
    api.router.lifespan_context = lifespan


class FirmwareUpload(BaseModel):
    firmware_b64: str

@api.post("/flash", dependencies=[Depends(verify_jwt)])
async def flash_firmware(request: Request, payload: FirmwareUpload):
    controller: Controller = request.app.state.controller

    if not controller.ready_devices:
        raise HTTPException(status_code=400, detail="no ready devices to flash")
    
    try:
        fw_bytes = base64.b64decode(payload.firmware_b64)
        fw = bytearray(fw_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid firmware encoding: {str(e)}")

    start_data = controller.start_ota(fw)
    if start_data["missed"]:
        raise HTTPException(status_code=400, detail=f"{len(start_data['missed'])} acknowledgments are missing ({', '.join(sorted(set(start_data['missed'])))}).")

    data = controller.transfer(fw, start_data["acked"])
    
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


@api.get("/settings")
async def status(request: Request):
    controller: Controller = request.app.state.controller
    return JSONResponse(content={"response": {"network_id": controller.settings.network_id}})


@api.post("/start")
async def start(request: Request, _token_payload=Depends(verify_jwt)):
    controller: Controller = request.app.state.controller

    controller.start()

    return JSONResponse(content={"response": "done"})


@api.post("/stop", dependencies=[Depends(verify_jwt)])
async def stop(request: Request):
    controller: Controller = request.app.state.controller

    controller.stop()

    return JSONResponse(content={"response": "done"})
class IssueRequest(BaseModel):
    start: str  # ISO8601 string

@api.post("/issue_jwt")
def issue_token(req: IssueRequest, db: Session = Depends(get_db)):
    try:
        start = datetime.datetime.fromisoformat(req.start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid 'start' time format (use ISO8601)")


    end = start + datetime.timedelta(minutes=30)
    payload = {
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "nbf": start,
        "exp": end,
    }
    token = jwt.encode(payload, PRIVATE_KEY, algorithm=ALGORITHM)

    db_record = JWTRecord(jwt=token, date_start=start, date_end=end)
    db.add(db_record)
    try:
        db.commit()
        db.refresh(db_record)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Timeslot already full")
        
    return {"data": token}


@api.get("/public_key", response_class=None)
def public_key():
    """Expose the public key (frontend can use this to verify JWT signatures)."""
    return JSONResponse(content={"data": PUBLIC_KEY})

class JWTRecordOut(BaseModel):
    date_start: datetime.datetime
    date_end: datetime.datetime
    model_config = {"arbitrary_types_allowed": True}

@api.get("/records", response_model=list[JWTRecordOut])
def list_records(db: Session = Depends(get_db)):
    now = datetime.datetime.now(datetime.timezone.utc) 
    yesterday = now - datetime.timedelta(days=1)
    one_month_later = now + datetime.timedelta(days=30)
    records = (
        db.query(JWTRecord)
        .filter(
            JWTRecord.date_start >= yesterday,
            JWTRecord.date_start <= one_month_later
        )
        .order_by(asc(JWTRecord.date_start))
        .all()
    )
    return records

# Mount static files after all routes are defined
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
api.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
