"""Tests for swarmit.client — build_client probe, Local backend, HTTP backend."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from swarmit.client import _fetch_server_settings, build_client
from swarmit.client.http import HTTPSwarmitClient, SwarmitAuthError
from swarmit.client.local import LocalSwarmitClient
from swarmit.testbed.controller import ControllerSettings

# ---- helpers ----


class _MockResponse:
    """File-like stand-in for urlopen's return value."""

    def __init__(self, body: bytes = b"", lines=None, status: int = 200):
        self.body = body
        self.lines = lines or []
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body

    def __iter__(self):
        return iter(self.lines)


def _http_error(code: int, body: bytes = b"") -> HTTPError:
    return HTTPError("http://x", code, "err", {}, io.BytesIO(body))


# ---- _fetch_server_settings / build_client ----


@patch("swarmit.client.urlopen")
def test_fetch_server_settings_reachable(urlopen_mock):
    urlopen_mock.return_value = _MockResponse(body=b'{"network_id": 4660}')
    result = _fetch_server_settings("http://127.0.0.1:8001")
    assert result == {"network_id": 4660}


@patch("swarmit.client.urlopen")
def test_fetch_server_settings_unreachable(urlopen_mock):
    urlopen_mock.side_effect = URLError("connection refused")
    assert _fetch_server_settings("http://127.0.0.1:8001") is None


@patch("swarmit.client.urlopen")
def test_build_client_picks_http_when_reachable(urlopen_mock):
    # Daemon returns network_id=1, matching ControllerSettings default.
    urlopen_mock.return_value = _MockResponse(body=b'{"network_id": 1}')
    client = build_client(ControllerSettings(), no_server=False)
    assert isinstance(client, HTTPSwarmitClient)


@patch("swarmit.client.local.Controller")
@patch("swarmit.client.urlopen")
def test_build_client_falls_back_to_local(urlopen_mock, _controller_mock):
    urlopen_mock.side_effect = URLError("connection refused")
    client = build_client(ControllerSettings(), no_server=False)
    assert isinstance(client, LocalSwarmitClient)


@patch("swarmit.client.local.Controller")
def test_build_client_respects_no_server(_controller_mock):
    # Even if a daemon would be reachable, --no-daemon forces Local.
    with patch("swarmit.client.urlopen") as urlopen_mock:
        urlopen_mock.return_value = _MockResponse(body=b'{"network_id": 1}')
        client = build_client(ControllerSettings(), no_server=True)
    assert isinstance(client, LocalSwarmitClient)
    urlopen_mock.assert_not_called()


@patch("swarmit.client.urlopen")
def test_build_client_refuses_on_network_mismatch(urlopen_mock):
    # Daemon is on network 9999; CLI asked for 1 → must raise, not silently
    # route through the wrong network.
    urlopen_mock.return_value = _MockResponse(body=b'{"network_id": 9999}')
    with pytest.raises(RuntimeError, match="network"):
        build_client(ControllerSettings(network_id=1), no_server=False)


@patch("swarmit.client.local.Controller")
@patch("swarmit.client.urlopen")
def test_build_client_skips_mismatch_check_with_no_server(
    urlopen_mock, _controller_mock
):
    # --no-daemon bypasses the probe entirely, so no mismatch check fires.
    urlopen_mock.return_value = _MockResponse(body=b'{"network_id": 9999}')
    client = build_client(ControllerSettings(network_id=1), no_server=True)
    assert isinstance(client, LocalSwarmitClient)


# ---- HTTPSwarmitClient ----


@patch("swarmit.client.http.urlopen")
def test_http_status_parses_response(urlopen_mock):
    body = json.dumps(
        {
            "response": {
                "BC3D3C8A2A6F8E68": {
                    "device": "DotBotV3",
                    "status": "Bootloader",
                    "battery": 2500,
                    "pos_x": 100,
                    "pos_y": 200,
                    "last_updated_at": 1.0,
                }
            }
        }
    ).encode()
    urlopen_mock.return_value = _MockResponse(body=body)
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    result = client.status()
    assert "BC3D3C8A2A6F8E68" in result
    assert result["BC3D3C8A2A6F8E68"].battery == 2500


@patch("swarmit.client.http.urlopen")
def test_http_start_omits_body_when_no_devices(urlopen_mock):
    urlopen_mock.return_value = _MockResponse(body=b"{}")
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    client.start()
    req = urlopen_mock.call_args.args[0]
    assert req.full_url.endswith("/start")
    assert req.data is None  # no body → daemon broadcasts to all


@patch("swarmit.client.http.urlopen")
def test_http_start_sends_body_with_devices(urlopen_mock):
    urlopen_mock.return_value = _MockResponse(body=b"{}")
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    client.start(devices=["A", "B"])
    req = urlopen_mock.call_args.args[0]
    payload = json.loads(req.data)
    assert payload == {"devices": ["A", "B"]}


@patch("swarmit.client.http.urlopen")
def test_http_flash_yields_parsed_sse_events(urlopen_mock):
    urlopen_mock.return_value = _MockResponse(
        lines=[
            b'data: {"type": "flash_started", "total_chunks": 1}\n',
            b"\n",
            b'data: {"type": "complete", "all_success": true, "elapsed_s": 0.1}\n',
            b"\n",
        ]
    )
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    events = list(client.flash(b"fw", devices=None))
    assert [e["type"] for e in events] == ["flash_started", "complete"]
    # Verify request body shape
    body = json.loads(urlopen_mock.call_args.args[0].data)
    assert "firmware_b64" in body
    assert body["ota_timeout"] is None  # default


@patch("swarmit.client.http.urlopen")
def test_http_401_raises_auth_error(urlopen_mock):
    urlopen_mock.side_effect = _http_error(401, b"bad token")
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    with pytest.raises(SwarmitAuthError):
        client.status()


@patch("swarmit.client.http.urlopen")
def test_http_403_raises_auth_error(urlopen_mock):
    urlopen_mock.side_effect = _http_error(403, b"forbidden")
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    with pytest.raises(SwarmitAuthError):
        client.status()


@patch("swarmit.client.http.urlopen")
def test_http_500_raises_runtime_error(urlopen_mock):
    urlopen_mock.side_effect = _http_error(500, b"boom")
    client = HTTPSwarmitClient("http://127.0.0.1:8001")
    with pytest.raises(RuntimeError) as excinfo:
        client.status()
    assert "500" in str(excinfo.value)
    assert not isinstance(excinfo.value, SwarmitAuthError)


# ---- LocalSwarmitClient ----


@patch("swarmit.client.local.Controller")
def test_local_status_returns_controller_status_data(controller_mock):
    inst = controller_mock.return_value
    inst.status_data = {"A": "status-A"}
    client = LocalSwarmitClient(ControllerSettings())
    assert client.status() == {"A": "status-A"}


@patch("swarmit.client.local.Controller")
def test_local_start_delegates(controller_mock):
    inst = controller_mock.return_value
    client = LocalSwarmitClient(ControllerSettings())
    client.start(devices=["A"])
    inst.start.assert_called_with(devices=["A"])


@patch("swarmit.client.local.Controller")
def test_local_message_delegates(controller_mock):
    inst = controller_mock.return_value
    client = LocalSwarmitClient(ControllerSettings())
    client.message("hi")
    inst.send_message.assert_called_with("hi")


@patch("swarmit.client.local.Controller")
def test_local_close_calls_terminate(controller_mock):
    inst = controller_mock.return_value
    client = LocalSwarmitClient(ControllerSettings())
    client.close()
    inst.terminate.assert_called_once()


@patch("swarmit.client.local.Controller")
def test_local_context_manager_terminates(controller_mock):
    inst = controller_mock.return_value
    with LocalSwarmitClient(ControllerSettings()):
        pass
    inst.terminate.assert_called_once()


@patch("swarmit.client.local.Controller")
def test_local_flash_emits_error_on_missed_acks(controller_mock):
    inst = controller_mock.return_value
    inst.start_ota.return_value = {
        "ota": MagicMock(fw_hash=b"\x00" * 32),
        "acked": ["A"],
        "missed": ["B"],
    }
    inst.chunks = [MagicMock()]
    client = LocalSwarmitClient(ControllerSettings())
    events = list(client.flash(b"fw"))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "missed" in events[0]["message"]
