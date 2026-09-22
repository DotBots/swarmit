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
    # Even if a server would be reachable, --no-server forces Local.
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
    # --no-server bypasses the probe entirely, so no mismatch check fires.
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
    assert req.data is None  # no body → server broadcasts to all


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


def _flash_controller(controller_mock, acked, missed=(), stale=()):
    """Wire a mocked Controller for a flash that reaches the transfer."""
    inst = controller_mock.return_value
    inst.start_ota.return_value = {
        "ota": MagicMock(fw_hash=b"\x00" * 32),
        "acked": list(acked),
        "missed": list(missed),
    }
    # Set even when empty: an unconfigured MagicMock is truthy but iterates
    # empty, which fakes a "skipping 0 device(s)" stale-bootloader warning.
    inst.stale_bootloaders.return_value = list(stale)
    inst.chunks = [MagicMock()]
    return inst


@patch("swarmit.client.local.Controller")
def test_local_flash_errors_when_no_device_acked_the_start(controller_mock):
    _flash_controller(controller_mock, acked=[], missed=["B"])
    client = LocalSwarmitClient(ControllerSettings())
    events = list(client.flash(b"fw"))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "missed" in events[0]["message"]


@patch("swarmit.client.local.Controller")
def test_local_flash_skips_devices_that_missed_the_start_ack(controller_mock):
    _flash_controller(controller_mock, acked=["A"], missed=["B"])
    client = LocalSwarmitClient(ControllerSettings())
    events = list(client.flash(b"fw"))
    assert events[0]["type"] == "warning"
    assert "B" in events[0]["message"]
    assert not [e for e in events if e["type"] == "error"]
    started = [e for e in events if e["type"] == "flash_started"]
    assert len(started) == 1
    assert started[0]["devices"] == ["A"]


@patch("swarmit.client.local.Controller")
def test_local_flash_errors_when_every_bootloader_is_stale(controller_mock):
    _flash_controller(controller_mock, acked=["A"], stale=["A"])
    client = LocalSwarmitClient(ControllerSettings())
    events = list(client.flash(b"fw"))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "bootloader older" in events[0]["message"]


@patch("swarmit.client.local.Controller")
def test_local_flash_skips_stale_bootloaders_and_flashes_the_rest(
    controller_mock,
):
    _flash_controller(controller_mock, acked=["A", "B"], stale=["B"])
    client = LocalSwarmitClient(ControllerSettings())
    events = list(client.flash(b"fw"))
    assert events[0]["type"] == "warning"
    assert "B" in events[0]["message"]
    assert not [e for e in events if e["type"] == "error"]
    started = [e for e in events if e["type"] == "flash_started"]
    assert len(started) == 1
    assert started[0]["devices"] == ["A"]


def test_parse_node_status_ignores_server_fields_the_client_does_not_know():
    """The client must ignore payload keys that are not dataclass fields.

    `/status` carries display strings computed server-side beside the raw
    fields. Splatting the whole `info` dict into DeviceInfo made every one of
    them a TypeError - not only across versions but within a single one, since
    the server and the client here are the same build: `swarmit status` died
    on `lh2_summary` against its own daemon.
    """
    from swarmit.client.http import _parse_node_status

    node = _parse_node_status(
        {
            "device": "DotBotV3",
            "status": "Running",
            "battery": 2300,
            "pos_x": 0,
            "pos_y": 0,
            "last_updated_at": 0.0,
            "sp": 0x2003FF00,
            "psr": 0x2B,
            "ipc_timeouts": 3,
            "tx_dropped": 290,
            # Computed server-side, not fields of NodeStatus / DeviceInfo.
            "reset_cause": "stopped",
            "fault_name": "NoFault",
            "battery_pct": 57,
            "battery_level": "ok",
            "a_field_from_a_future_daemon": 1,
            "info": {
                "image_name": "dotbot-sandbox-dotbot-v3.bin",
                "lh2_homography_count": 1,
                "lh2_flags": 3,
                "lh2_summary": "1 basestation (valid, from flash)",
                "image_state_name": "Idle",
                "image_result_name": "Success",
                "another_future_field": "x",
            },
        }
    )

    assert node.battery == 2300
    # Every raw status field the daemon sends reaches the client, including
    # the crash report's stack registers and the two drop counters.
    assert (node.sp, node.psr) == (0x2003FF00, 0x2B)
    assert (node.ipc_timeouts, node.tx_dropped) == (3, 290)
    assert node.info is not None
    assert node.info.image_name == "dotbot-sandbox-dotbot-v3.bin"
    # The property still derives it locally from the raw fields.
    assert node.info.lh2_summary == "1 basestation (valid, from flash)"


def test_parse_node_status_still_reads_a_daemon_without_device_info():
    from swarmit.client.http import _parse_node_status

    node = _parse_node_status(
        {
            "device": "DotBotV3",
            "status": "Bootloader",
            "battery": 0,
            "pos_x": 0,
            "pos_y": 0,
            "last_updated_at": 0.0,
        }
    )

    assert node.info is None
