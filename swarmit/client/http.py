"""HTTP-backed SwarmitClient — talks to a running `swarmit-daemon`."""

from __future__ import annotations

import base64
import json
import time
from typing import Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from swarmit.testbed.controller import NodeStatus, ResetLocation
from swarmit.testbed.protocol import DeviceType, StatusType


class SwarmitAuthError(RuntimeError):
    """Daemon returned 401 (token rejected) or 403 (token missing).

    Daemon in localhost-only mode doesn't require auth; this normally
    surfaces when talking to a daemon configured with auth_mode='jwt'
    (e.g. a future cross-machine deployment) without a valid token.
    """


class HTTPSwarmitClient:
    """Make HTTP requests against the daemon's REST surface."""

    def __init__(self, base_url: str, default_timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = default_timeout

    def __enter__(self) -> "HTTPSwarmitClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- read ----

    def status(self) -> dict[str, NodeStatus]:
        data = self._request("GET", "/status")
        return {addr: _parse_node_status(d) for addr, d in data["response"].items()}

    def watch_status(
        self, interval: float = 0.5
    ) -> Iterator[dict[str, NodeStatus]]:
        # Polling instead of SSE to keep this stdlib-only. Phase D can
        # switch to the daemon's /events stream for push-based updates.
        while True:
            yield self.status()
            time.sleep(interval)

    # ---- write ----

    # NOTE on devices=[]: `if devices` is False for both None and an empty
    # list, so both collapse to "no body" → daemon interprets as "all
    # devices". No current caller passes [] meaning "literally no devices",
    # but if one ever needs that semantic we'll need to distinguish here.

    def start(self, devices: Optional[list[str]] = None) -> None:
        self._request("POST", "/start", body={"devices": devices} if devices else None)

    def stop(self, devices: Optional[list[str]] = None) -> None:
        self._request("POST", "/stop", body={"devices": devices} if devices else None)

    def reset(self, locations: dict[str, ResetLocation]) -> None:
        body = {
            "locations": {
                addr: {"pos_x": loc.pos_x, "pos_y": loc.pos_y}
                for addr, loc in locations.items()
            }
        }
        self._request("POST", "/reset", body=body)

    def flash(
        self,
        firmware: bytes,
        devices: Optional[list[str]] = None,
    ) -> Iterator[dict]:
        """POST /flash/stream and yield SSE events.

        OTA can take minutes; the timeout is set high enough to cover a
        full image transfer. The generator exits cleanly after the
        terminal "complete" or "error" event.
        """
        body = json.dumps(
            {
                "firmware_b64": base64.b64encode(bytes(firmware)).decode(
                    "ascii"
                ),
                "devices": devices,
            }
        ).encode("utf-8")
        req = Request(
            f"{self._base}/flash/stream",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            resp = urlopen(req, timeout=600.0)
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SwarmitAuthError(
                    f"daemon returned HTTP {e.code} on /flash/stream: {detail}"
                ) from e
            raise RuntimeError(
                f"daemon returned HTTP {e.code} on /flash/stream: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"daemon unreachable on /flash/stream: {e.reason}"
            ) from e

        with resp:
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    def message(self, text: str) -> None:
        self._request("POST", "/message", body={"message": text})

    def send_lh2_calibration(self, blob: bytes) -> None:
        body = {"calibration_b64": base64.b64encode(bytes(blob)).decode("ascii")}
        self._request("POST", "/lh2_calibration", body=body)

    def close(self) -> None:
        # No persistent connection to close (stdlib urllib opens per-request).
        pass

    # ---- internal ----

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        url = f"{self._base}{path}"
        data: Optional[bytes] = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=timeout or self._timeout) as r:
                raw = r.read()
                if not raw:
                    return {}
                return json.loads(raw)
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SwarmitAuthError(
                    f"daemon returned HTTP {e.code} on {method} {path}: {detail}"
                ) from e
            raise RuntimeError(
                f"daemon returned HTTP {e.code} on {method} {path}: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"daemon unreachable ({method} {path}): {e.reason}"
            ) from e


def _parse_node_status(d: dict) -> NodeStatus:
    """JSON dict from /status → NodeStatus dataclass."""
    return NodeStatus(
        device=DeviceType[d["device"]],
        status=StatusType[d["status"]],
        battery=d["battery"],
        pos_x=d["pos_x"],
        pos_y=d["pos_y"],
        last_updated_at=d["last_updated_at"],
    )
