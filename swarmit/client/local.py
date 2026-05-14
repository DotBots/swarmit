"""In-process SwarmitClient backed by a Controller."""

from __future__ import annotations

import threading
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
        ota_timeout: Optional[float] = None,
        ota_max_retries: Optional[int] = None,
    ) -> Iterator[dict]:
        """Run an OTA and yield progress events.

        Same event shape as HTTPSwarmitClient.flash → daemon's
        /flash/stream SSE: flash_started, chunk, device_done, complete,
        error.
        """
        # Per-flash override of OTA params on the controller's settings;
        # restored on exit.
        saved_timeout = self._controller.settings.ota_timeout
        saved_retries = self._controller.settings.ota_max_retries
        if ota_timeout is not None:
            self._controller.settings.ota_timeout = ota_timeout
        if ota_max_retries is not None:
            self._controller.settings.ota_max_retries = ota_max_retries
        try:
            yield from self._run_flash(firmware, devices)
        finally:
            self._controller.settings.ota_timeout = saved_timeout
            self._controller.settings.ota_max_retries = saved_retries

    def _run_flash(
        self,
        firmware: bytes,
        devices: Optional[list[str]] = None,
    ) -> Iterator[dict]:
        fw = bytearray(firmware)
        try:
            start_data = (
                self._controller.start_ota(fw, devices)
                if devices
                else self._controller.start_ota(fw)
            )
        except Exception as exc:
            yield {"type": "error", "message": f"start_ota: {exc}"}
            return

        if start_data["missed"]:
            missed = sorted(set(start_data["missed"]))
            yield {
                "type": "error",
                "message": f"{len(missed)} OTA start acks missed: {missed}",
            }
            return

        yield {
            "type": "flash_started",
            "image_size": len(fw),
            "total_chunks": len(self._controller.chunks),
            "fw_hash": start_data["ota"].fw_hash.hex().upper(),
            "devices": sorted(start_data["acked"]),
        }

        # Run transfer in a thread; poll transfer_data while it runs.
        result: dict = {}
        def _runner():
            try:
                result["data"] = self._controller.transfer(
                    fw, start_data["acked"]
                )
            except Exception as exc:
                result["exc"] = exc

        t = threading.Thread(target=_runner)
        t.start()

        last_acked = {addr: 0 for addr in start_data["acked"]}
        start_ts = time.time()
        while t.is_alive():
            time.sleep(0.1)
            for addr in start_data["acked"]:
                td = self._controller.transfer_data.get(addr)
                if td is None:
                    continue
                acked = sum(1 for c in td.chunks if c.acked)
                if acked > last_acked[addr]:
                    yield {
                        "type": "chunk",
                        "addr": addr,
                        "acked": acked,
                        "total": len(td.chunks),
                    }
                    last_acked[addr] = acked
        t.join()

        if "exc" in result:
            yield {"type": "error", "message": f"transfer: {result['exc']}"}
            return

        transfer = result["data"]
        for addr, td in transfer.items():
            yield {
                "type": "device_done",
                "addr": addr,
                "success": td.success,
                "retries": sum(c.retries for c in td.chunks),
                "chunks_acked": sum(1 for c in td.chunks if c.acked),
                "chunks_total": len(td.chunks),
            }
        yield {
            "type": "complete",
            "all_success": all(td.success for td in transfer.values()),
            "elapsed_s": time.time() - start_ts,
        }

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
