"""Unified client interface for swarmit operations.

Two backends behind a single Protocol:

- LocalSwarmitClient: builds a `Controller` in-process. This is what the
  CLI has always done — ephemeral, one Controller per invocation, with
  the discovery wait that comes with it.

- HTTPSwarmitClient: talks to a long-lived `swarmit-server` over HTTP.
  The server's Controller stays subscribed continuously, so the CLI's
  cold-start tax disappears and stale-discovery flakes go with it.

`build_client(settings, no_server=False)` probes the server at
SWARMIT_SERVER_URL (default `http://127.0.0.1:8001`) and returns the
right backend. The probe is `GET /settings` with a 200 ms timeout; one
TCP connect-refused when no server is running, ~5 ms.
"""

from __future__ import annotations

import json
import os
from typing import Iterator, Protocol, runtime_checkable
from urllib.error import URLError
from urllib.request import Request, urlopen

from swarmit.testbed.controller import (
    ControllerSettings,
    NodeStatus,
    ResetLocation,
)

SERVER_URL_DEFAULT = "http://127.0.0.1:8001"


@runtime_checkable
class SwarmitClient(Protocol):
    """Operations all swarmit CLI commands need.

    All read methods return ALL devices currently known; callers apply
    any `--devices` filter from their `ControllerSettings`.
    """

    def status(self) -> dict[str, NodeStatus]: ...

    def start(self, devices: list[str] | None = None) -> None: ...

    def stop(self, devices: list[str] | None = None) -> None: ...

    def reset(self, locations: dict[str, ResetLocation]) -> None: ...

    def flash(
        self,
        firmware: bytes,
        devices: list[str] | None = None,
        ota_timeout: float | None = None,
        ota_max_retries: int | None = None,
    ) -> Iterator[dict]:
        """Stream OTA progress events. See webserver.flash_stream for the
        event type vocabulary (flash_started / chunk / device_done /
        complete / error). Caller consumes until "complete" or "error".

        `ota_timeout` and `ota_max_retries` override the controller's
        defaults for the duration of this flash only (None = leave the
        controller's current values in place).
        """
        ...

    def message(self, text: str) -> None: ...

    def send_lh2_calibration(self, blob: bytes) -> None: ...

    def watch_status(
        self, interval: float = 0.5
    ) -> Iterator[dict[str, NodeStatus]]: ...

    def watch_log_events(self) -> Iterator[dict]:
        """Yield SWARMIT_EVENT_LOG events as they arrive.

        Each event is `{type, addr, timestamp, data_size, data_hex}`.
        Iterator blocks between events; caller stops via break or
        KeyboardInterrupt.
        """
        ...

    def close(self) -> None: ...


def build_client(
    settings: ControllerSettings,
    no_server: bool = False,
) -> SwarmitClient:
    """Probe for a running server; return HTTPSwarmitClient if reachable
    AND its settings match the caller, else LocalSwarmitClient.

    Raises RuntimeError if a server is running but its network_id (or
    any other field exposed via /settings) diverges from the caller's
    settings. Bypass with `no_server=True`.
    """
    from swarmit.client.local import LocalSwarmitClient

    if not no_server:
        url = os.environ.get("SWARMIT_SERVER_URL", SERVER_URL_DEFAULT)
        server_settings = _fetch_server_settings(url)
        if server_settings is not None:
            _ensure_config_matches(settings, server_settings, url)
            from swarmit.client.http import HTTPSwarmitClient

            return HTTPSwarmitClient(url)
    return LocalSwarmitClient(settings)


def _fetch_server_settings(url: str, timeout: float = 0.2) -> dict | None:
    """GET /settings; return parsed dict if reachable, None otherwise."""
    try:
        req = Request(f"{url.rstrip('/')}/settings", method="GET")
        with urlopen(req, timeout=timeout) as r:
            if getattr(r, "status", 200) != 200:
                return None
            return json.loads(r.read())
    except (URLError, ConnectionError, TimeoutError, OSError):
        return None


def _ensure_config_matches(
    local: ControllerSettings, server: dict, url: str
) -> None:
    """Refuse to route through a server that disagrees on operational config.

    Today /settings only exposes `network_id`, so that's the only field
    we can check. If the dashboard adds more fields, extend here.
    """
    server_net = server.get("network_id")
    if server_net is not None and server_net != local.network_id:
        raise RuntimeError(
            f"server at {url} is on network 0x{server_net:04X}, but this "
            f"invocation requested 0x{local.network_id:04X}. "
            f"Stop the server or pass --no-server."
        )
