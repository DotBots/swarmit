# SPDX-FileCopyrightText: 2022-present Inria
# SPDX-FileCopyrightText: 2022-present Alexandre Abadie <alexandre.abadie@inria.fr>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Module for the web server application."""

import base64
import os
from dataclasses import asdict
from typing import List
from pydantic import BaseModel

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from dotbot import pydotbot_version

from testbed.swarmit.controller import Controller, ControllerSettings

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

@api.post("/flash")
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


@api.post("/start")
async def start(request: Request):
    controller: Controller = request.app.state.controller

    controller.start()

    return JSONResponse(content={"response": "done"})


@api.post("/stop")
async def stop(request: Request):
    controller: Controller = request.app.state.controller

    controller.stop()

    return JSONResponse(content={"response": "done"})


# Mount static files after all routes are defined
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
api.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
