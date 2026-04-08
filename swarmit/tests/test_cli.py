import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swarmit.cli.main import main

CLI_HELP_EXPECTED = """Usage: main [OPTIONS] COMMAND [ARGS]...

Options:
  -c, --config-path FILE  Path to a .toml configuration file.
  --api-url TEXT          Base URL of the SwarmIT dashboard REST API.  [default:
                          http://localhost:8001]
  --token TEXT            JWT authentication token. Also readable from
                          SWARMIT_TOKEN env var.
  -d, --devices TEXT      Subset list of device addresses to interact with,
                          separated with ,
  -v, --verbose           Enable verbose mode.
  -V, --version           Show the version and exit.
  -h, --help              Show this message and exit.

Commands:
  flash    Flash a firmware to the robots.
  message  Send a custom text message to the robots.
  monitor  Monitor running applications.
  reset    Reset robots locations.
  start    Start the user application.
  status   Print current status of the robots.
  stop     Stop the user application.
"""

OTA_START_STATUS_DONE = {
    "status": "done",
    "acked": ["00000001"],
    "missed": [],
    "total_chunks": 1,
    "fw_hash": "ABCDEF1234",
}

OTA_TRANSFER_STATUS_SUCCESS = {
    "status": "success",
    "error": None,
    "total_chunks": 1,
    "devices": {
        "00000001": {
            "chunks_acked": 1,
            "total_chunks": 1,
            "success": True,
        }
    },
}

OTA_TRANSFER_STATUS_FAILED = {
    "status": "failed",
    "error": "transfer failed",
    "total_chunks": 1,
    "devices": {},
}


def make_response(status_code=200, json_data=None):
    """Build a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.skipif(sys.platform != "linux", reason="Serial port is different")
def test_main_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert result.output == CLI_HELP_EXPECTED


@patch("swarmit.cli.main.httpx")
def test_start(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    # _live_status polls /status; KeyboardInterrupt exits it cleanly
    httpx_mock.get.side_effect = KeyboardInterrupt
    runner = CliRunner()
    result = runner.invoke(main, ["--token", "TOK", "start"])
    assert result.exit_code == 0
    httpx_mock.post.assert_called_once()
    assert "/start" in httpx_mock.post.call_args.args[0]


@patch("swarmit.cli.main.httpx")
def test_start_with_devices(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    httpx_mock.get.side_effect = KeyboardInterrupt
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "-d", "00000001,00000002", "start"]
    )
    assert result.exit_code == 0
    call_kwargs = httpx_mock.post.call_args.kwargs
    assert call_kwargs["json"]["devices"] == ["00000001", "00000002"]


@patch("swarmit.cli.main.httpx")
def test_stop(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    httpx_mock.get.side_effect = KeyboardInterrupt
    runner = CliRunner()
    result = runner.invoke(main, ["--token", "TOK", "stop"])
    assert result.exit_code == 0
    httpx_mock.post.assert_called_once()
    assert "/stop" in httpx_mock.post.call_args.args[0]


@patch("swarmit.cli.main.httpx")
def test_reset(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--token", "TOK", "reset", "AABB:10,20"])
    assert result.exit_code == 0
    httpx_mock.post.assert_called_once()
    call_args = httpx_mock.post.call_args
    assert "/reset" in call_args.args[0]
    locations = call_args.kwargs["json"]["locations"]
    assert locations["AABB"] == {"pos_x": 10, "pos_y": 20}


@patch("swarmit.cli.main.httpx")
def test_reset_multiple_devices(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "reset", "AABB:10,20-CCDD:30,40"]
    )
    assert result.exit_code == 0
    locations = httpx_mock.post.call_args.kwargs["json"]["locations"]
    assert locations["AABB"] == {"pos_x": 10, "pos_y": 20}
    assert locations["CCDD"] == {"pos_x": 30, "pos_y": 40}


@pytest.fixture
def fw(tmp_path):
    fw_path = tmp_path / "fw.bin"
    fw_path.write_bytes(b"firmware")
    return fw_path


@patch("swarmit.cli.main.httpx")
def test_flash_missing_firmware(httpx_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["flash"])
    assert result.exit_code == 1
    assert "Missing firmware file" in result.output
    httpx_mock.post.assert_not_called()


@patch("swarmit.cli.main.httpx")
def test_flash_user_abort(httpx_mock, fw):
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)], input="n\n")
    assert "Do you want to continue?" in result.output
    assert "Abort" in result.output
    assert result.exit_code == 1
    httpx_mock.post.assert_not_called()


@patch("swarmit.cli.main.httpx")
def test_flash_api_error(httpx_mock, fw):
    # /ota/start returns 400
    httpx_mock.post.return_value = make_response(
        status_code=400, json_data={"detail": "no ready devices to flash"}
    )
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", str(fw)], input="y\n"
    )
    assert result.exit_code == 1
    assert "no ready devices to flash" in result.output


@patch("swarmit.cli.main.httpx")
def test_flash_missing_acks(httpx_mock, fw):
    # /ota/start returns pending, /ota/start/status shows missed
    httpx_mock.post.return_value = make_response(
        json_data={"status": "pending"}
    )
    httpx_mock.get.return_value = make_response(
        json_data={
            "status": "done",
            "acked": ["00000001"],
            "missed": ["00000002"],
            "total_chunks": 1,
            "fw_hash": "ABCDEF",
        }
    )
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", str(fw)], input="y\n"
    )
    assert result.exit_code == 1
    assert "acknowledgment" in result.output


@patch("swarmit.cli.main.httpx")
def test_flash_already_running(httpx_mock, fw):
    # /ota/start ok, /ota/start/status done, /ota/transfer returns 409
    httpx_mock.post.side_effect = [
        make_response(json_data={"status": "pending"}),
        make_response(
            status_code=409, json_data={"detail": "OTA already in progress"}
        ),
    ]
    httpx_mock.get.return_value = make_response(
        json_data=OTA_START_STATUS_DONE
    )
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", str(fw)], input="y\n"
    )
    assert result.exit_code == 1
    assert "OTA transfer already in progress" in result.output


@patch("swarmit.cli.main.httpx")
def test_flash_success(httpx_mock, fw):
    httpx_mock.post.side_effect = [
        make_response(json_data={"status": "pending"}),
        make_response(json_data={"status": "started"}),
    ]
    httpx_mock.get.side_effect = [
        make_response(json_data=OTA_START_STATUS_DONE),
        make_response(json_data=OTA_TRANSFER_STATUS_SUCCESS),
    ]
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", str(fw)], input="y\n"
    )
    assert result.exit_code == 0
    assert "Flash successful" in result.output
    assert httpx_mock.post.call_count == 2
    assert "/ota/start" in httpx_mock.post.call_args_list[0].args[0]
    assert "/ota/transfer" in httpx_mock.post.call_args_list[1].args[0]


@patch("swarmit.cli.main.httpx")
def test_flash_success_with_start(httpx_mock, fw):
    httpx_mock.post.side_effect = [
        make_response(json_data={"status": "pending"}),
        make_response(json_data={"status": "started"}),
        make_response(json_data={"response": "done"}),
    ]
    httpx_mock.get.side_effect = [
        make_response(json_data=OTA_START_STATUS_DONE),
        make_response(json_data=OTA_TRANSFER_STATUS_SUCCESS),
    ]
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", "--start", str(fw)], input="y\n"
    )
    assert result.exit_code == 0
    assert "Flash successful" in result.output
    # /ota/start, /ota/transfer, /start
    assert httpx_mock.post.call_count == 3
    assert "/start" in httpx_mock.post.call_args_list[2].args[0]


@patch("swarmit.cli.main.httpx")
def test_flash_failed(httpx_mock, fw):
    httpx_mock.post.side_effect = [
        make_response(json_data={"status": "pending"}),
        make_response(json_data={"status": "started"}),
    ]
    httpx_mock.get.side_effect = [
        make_response(json_data=OTA_START_STATUS_DONE),
        make_response(json_data=OTA_TRANSFER_STATUS_FAILED),
    ]
    runner = CliRunner()
    result = runner.invoke(
        main, ["--token", "TOK", "flash", str(fw)], input="y\n"
    )
    assert result.exit_code == 1
    assert "Flash failed" in result.output


@patch("swarmit.cli.main.httpx")
def test_flash_no_confirm_needed_with_yes(httpx_mock, fw):
    httpx_mock.post.side_effect = [
        make_response(json_data={"status": "pending"}),
        make_response(json_data={"status": "started"}),
    ]
    httpx_mock.get.side_effect = [
        make_response(json_data=OTA_START_STATUS_DONE),
        make_response(
            json_data={
                "status": "success",
                "error": None,
                "total_chunks": 0,
                "devices": {},
            }
        ),
    ]
    runner = CliRunner()
    result = runner.invoke(main, ["--token", "TOK", "flash", "-y", str(fw)])
    assert result.exit_code == 0
    assert "Do you want to continue?" not in result.output


@patch("swarmit.cli.main.httpx")
def test_monitor_keyboard_interrupt(httpx_mock):
    httpx_mock.get.side_effect = [
        make_response(json_data={"response": {}}),
        KeyboardInterrupt,
    ]
    runner = CliRunner()
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    assert "Stopping monitor" in result.output


@patch("swarmit.cli.main.httpx")
def test_status(httpx_mock):
    httpx_mock.get.return_value = make_response(json_data={"response": {}})
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    httpx_mock.get.assert_called_once()
    assert "/status" in httpx_mock.get.call_args.args[0]


@patch("swarmit.cli.main.httpx")
def test_status_watch(httpx_mock):
    httpx_mock.get.side_effect = [
        make_response(json_data={"response": {}}),
        KeyboardInterrupt,
    ]
    runner = CliRunner()
    result = runner.invoke(main, ["status", "-w"])
    assert result.exit_code == 0
    assert httpx_mock.get.call_count >= 1


@patch("swarmit.cli.main.httpx")
def test_message(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    runner = CliRunner()
    msg = "Hello swarm"
    result = runner.invoke(main, ["--token", "TOK", "message", msg])
    assert result.exit_code == 0
    call_args = httpx_mock.post.call_args
    assert "/message" in call_args.args[0]
    assert call_args.kwargs["json"]["message"] == msg


@patch("swarmit.cli.main.httpx")
def test_token_from_env(httpx_mock, monkeypatch):
    monkeypatch.setenv("SWARMIT_TOKEN", "ENV_TOKEN")
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    httpx_mock.get.side_effect = KeyboardInterrupt
    runner = CliRunner()
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    headers = httpx_mock.post.call_args.kwargs["headers"]
    assert headers == {"Authorization": "Bearer ENV_TOKEN"}


@patch("swarmit.cli.main.httpx")
def test_no_token_no_auth_header(httpx_mock):
    httpx_mock.post.return_value = make_response(
        json_data={"response": "done"}
    )
    httpx_mock.get.side_effect = KeyboardInterrupt
    runner = CliRunner()
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    headers = httpx_mock.post.call_args.kwargs["headers"]
    assert headers == {}
