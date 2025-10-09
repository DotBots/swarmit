# SPDX-FileCopyrightText: 2022-present Inria
# SPDX-FileCopyrightText: 2022-present Alexandre Abadie <alexandre.abadie@inria.fr>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Module for the web server application."""

import os
import base64
import tempfile
from typing import List
from pydantic import BaseModel

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from dotbot import pydotbot_version

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


@api.get("/")
async def root():
    FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    print(FRONTEND_DIR)
    return {"message": "Hello World"}


class FlashRequest(BaseModel):
    yes: bool = False
    start: bool = False
    ota_timeout: float = 0.7 # TODO: use default
    ota_max_retries: int = 10 # TODO: use default
    firmware_base64: str

@api.post("/flash")
async def flash_firmware():
    # firmware_path = None

    # # If firmware is base64-encoded, decode and save to a temp file
    # if req.firmware_base64:
    #     try:
    #         data = base64.b64decode(req.firmware_base64)
    #         with tempfile.NamedTemporaryFile(delete=False) as tmp:
    #             tmp.write(data)
    #             firmware_path = tmp.name
    #     except Exception as e:
    #         raise HTTPException(status_code=400, detail=f"Invalid base64 firmware: {e}")

    # try:
    #     flash(req.yes, req.start, req.ota_timeout, req.ota_max_retries, firmware_path)
    #     return JSONResponse(content={"response": "success"})
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=str(e))
    
    return JSONResponse(content={"response": "success"})


# Mount static files after all routes are defined
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
api.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
