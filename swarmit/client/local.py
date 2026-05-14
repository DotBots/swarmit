"""In-process SwarmitClient backed by a Controller."""

from __future__ import annotations

import time
from typing import Iterator, Optional

from swarmit.testbed.controller import (
    STATUS_TIMEOUT,
    Controller,
    ControllerSettings,
    NodeStatus,
    ResetLocation,
)


class LocalSwarmitClient:
    """Wrap a `Controller` so callers get the unified client API."""

    def __init__(self, settings: ControllerSettings):
        self._controller = Controller(settings)

    def __enter__(self) -> "LocalSwarmitClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def status(self) -> dict[str, NodeStatus]:
        # Cold-start: if status_data is empty (controller was just
        # constructed and MQTT/serial hasn't received any frames yet),
        # wait up to STATUS_TIMEOUT — matches the baseline CLI's
        # _live_status timeout. HTTPSwarmitClient skips this entirely
        # because the daemon's controller has been receiving frames
        # continuously, so its status_data is always warm.
        if not self._controller.status_data:
            time.sleep(STATUS_TIMEOUT)
        return dict(self._controller.status_data)

    def start(self, devices: Optional[list[str]] = None) -> None:
        self._controller.start(devices=devices)

    def stop(self, devices: Optional[list[str]] = None) -> None:
        self._controller.stop(devices=devices)

    def reset(self, locations: dict[str, ResetLocation]) -> None:
        self._controller.reset(locations)

    def flash(
        self,
        firmware: bytes,
        devices: Optional[list[str]] = None,
    ) -> dict:
        fw = bytearray(firmware)
        start_data = (
            self._controller.start_ota(fw, devices)
            if devices
            else self._controller.start_ota(fw)
        )
        if start_data["missed"]:
            raise RuntimeError(
                f"{len(start_data['missed'])} OTA start acks missed: "
                f"{sorted(set(start_data['missed']))}"
            )
        transfer = self._controller.transfer(fw, start_data["acked"])
        return {"start": start_data, "transfer": transfer}

    def message(self, text: str) -> None:
        self._controller.send_message(text)

    def send_lh2_calibration(self, blob: bytes) -> None:
        self._controller.send_lh2_calibration(bytearray(blob))

    def watch_status(
        self, interval: float = 0.5
    ) -> Iterator[dict[str, NodeStatus]]:
        # First snapshot honors the cold-start wait via status();
        # subsequent ones read status_data directly so the user gets
        # responsive updates instead of always paying STATUS_TIMEOUT.
        yield self.status()
        while True:
            time.sleep(interval)
            yield dict(self._controller.status_data)

    def close(self) -> None:
        self._controller.terminate()
