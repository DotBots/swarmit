"""HTTP-backed SwarmitClient — talks to a running `swarmit-server`."""

from __future__ import annotations

import base64
import dataclasses
import json
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from swarmit.testbed.controller import DeviceInfo, NodeStatus, ResetLocation
from swarmit.testbed.protocol import DeviceType, StatusType


class SwarmitAuthError(RuntimeError):
    """Daemon returned 401 (token rejected) or 403 (token missing).

    Daemon in localhost-only mode doesn't require auth; this normally
    surfaces when talking to a server configured with auth_mode='jwt'
    (e.g. a future cross-machine deployment) without a valid token.
    """


class HTTPSwarmitClient:
    """Make HTTP requests against the server's REST surface."""

    def __init__(self, base_url: str, default_timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = default_timeout

    def __enter__(self) -> HTTPSwarmitClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- read ----

    def status(self) -> dict[str, NodeStatus]:
        data = self._request("GET", "/status")
        return {
            addr: _parse_node_status(d) for addr, d in data["response"].items()
        }

    def watch_status(
        self, interval: float = 0.5
    ) -> Iterator[dict[str, NodeStatus]]:
        """Stream status snapshots from the server's /events SSE feed.

        `interval` is kept for signature parity with LocalSwarmitClient
        but is effectively a hint — the cadence is whatever the server's
        /events handler decides (currently ~500 ms).
        """
        req = Request(
            f"{self._base}/events",
            method="GET",
            headers={"Accept": "text/event-stream"},
        )
        try:
            resp = urlopen(req, timeout=None)
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SwarmitAuthError(
                    f"server returned HTTP {e.code} on /events: {detail}"
                ) from e
            raise RuntimeError(
                f"server returned HTTP {e.code} on /events: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"server unreachable on /events: {e.reason}"
            ) from e

        with resp:
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") != "status":
                    continue
                yield {
                    addr: _parse_node_status(d)
                    for addr, d in event["devices"].items()
                }

    def watch_log_events(self) -> Iterator[dict]:
        """Filter the server's /events stream for log_event type."""
        req = Request(
            f"{self._base}/events",
            method="GET",
            headers={"Accept": "text/event-stream"},
        )
        try:
            resp = urlopen(req, timeout=None)
        except HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise SwarmitAuthError(
                    f"server returned HTTP {e.code} on /events: {detail}"
                ) from e
            raise RuntimeError(
                f"server returned HTTP {e.code} on /events: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"server unreachable on /events: {e.reason}"
            ) from e

        with resp:
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "log_event":
                    yield event

    # ---- write ----

    # NOTE on devices=[]: `if devices` is False for both None and an empty
    # list, so both collapse to "no body" → server interprets as "all
    # devices". No current caller passes [] meaning "literally no devices",
    # but if one ever needs that semantic we'll need to distinguish here.

    def start(self, devices: list[str] | None = None) -> None:
        self._request(
            "POST", "/start", body={"devices": devices} if devices else None
        )

    def stop(self, devices: list[str] | None = None) -> None:
        self._request(
            "POST", "/stop", body={"devices": devices} if devices else None
        )

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
        devices: list[str] | None = None,
        ota_timeout: float | None = None,
        ota_max_retries: int | None = None,
        image_name: str = "",
        image_version: str = "",
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
                "ota_timeout": ota_timeout,
                "ota_max_retries": ota_max_retries,
                "image_name": image_name,
                "image_version": image_version,
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
                    f"server returned HTTP {e.code} on /flash/stream: {detail}"
                ) from e
            raise RuntimeError(
                f"server returned HTTP {e.code} on /flash/stream: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"server unreachable on /flash/stream: {e.reason}"
            ) from e

        with resp:
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    def message(self, text: str) -> None:
        self._request("POST", "/message", body={"message": text})

    def send_lh2_calibration(
        self, blob: bytes, devices: list[str] | None = None
    ) -> None:
        body = {
            "calibration_b64": base64.b64encode(bytes(blob)).decode("ascii"),
            "devices": list(devices) if devices else None,
        }
        self._request("POST", "/lh2_calibration", body=body)

    def request_lh2_capture(self, device_addr: str) -> None:
        self._request("POST", "/lh2_capture", body={"device": device_addr})

    def refresh_device_info(self, devices: list[str] | None = None) -> None:
        """Ask the selected devices for their device-info block and wait.

        A daemon predating this route answers 404; the cached block from the
        background refresh is then whatever `status()` already returned, so
        `info` degrades to showing that rather than failing.
        """
        try:
            self._request(
                "POST", "/device_info", body={"devices": devices or None}
            )
        except RuntimeError:
            pass

    def close(self) -> None:
        # No persistent connection to close (stdlib urllib opens per-request).
        pass

    # ---- internal ----

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        url = f"{self._base}{path}"
        data: bytes | None = None
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
                    f"server returned HTTP {e.code} on {method} {path}: {detail}"
                ) from e
            raise RuntimeError(
                f"server returned HTTP {e.code} on {method} {path}: {detail}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"server unreachable ({method} {path}): {e.reason}"
            ) from e


_DEVICE_INFO_FIELDS = {f.name for f in dataclasses.fields(DeviceInfo)}


def _parse_device_info(info: dict) -> DeviceInfo:
    """JSON dict → DeviceInfo, ignoring keys this client does not know.

    `/status` carries server-computed display strings beside the raw fields
    and is meant to grow, so the client reads only the fields it knows.
    """
    return DeviceInfo(
        **{k: v for k, v in info.items() if k in _DEVICE_INFO_FIELDS}
    )


def _parse_node_status(d: dict) -> NodeStatus:
    """JSON dict from /status → NodeStatus dataclass."""
    info = d.get("info")
    return NodeStatus(
        device=DeviceType[d["device"]],
        status=StatusType[d["status"]],
        battery=d["battery"],
        pos_x=d["pos_x"],
        pos_y=d["pos_y"],
        reset_reason=d.get("reset_reason", 0),
        fault=d.get("fault", 0),
        from_ns=d.get("from_ns", 0),
        cfsr=d.get("cfsr", 0),
        sfsr=d.get("sfsr", 0),
        pc=d.get("pc", 0),
        lr=d.get("lr", 0),
        sp=d.get("sp", 0),
        psr=d.get("psr", 0),
        raw=d.get("raw", ""),
        last_updated_at=d["last_updated_at"],
        info_gen=d.get("info_gen", 0),
        # A daemon predating device info sends no "info" key at all, and a
        # bot that has not answered yet leaves it null.
        info=_parse_device_info(info) if isinstance(info, dict) else None,
    )
