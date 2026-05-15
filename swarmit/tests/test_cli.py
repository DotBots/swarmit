import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from swarmit.cli.main import main
from swarmit.testbed.controller import NodeStatus
from swarmit.testbed.protocol import DeviceType, StatusType

CLI_HELP_EXPECTED = """Usage: main [OPTIONS] COMMAND [ARGS]...

Options:
  -c, --config-path FILE      Path to a .toml configuration file.
  -p, --port TEXT             Serial port to use to send the bitstream to the
                              gateway. Default: /dev/ttyACM0.
  -b, --baudrate INTEGER      Serial port baudrate. Default: 1000000.
  -H, --mqtt-host TEXT        MQTT host. Default: localhost.
  -P, --mqtt-port INTEGER     MQTT port. Default: 1883.
  -T, --mqtt-use_tls          Use TLS with MQTT.
  -n, --network-id TEXT       Marilib network ID to use. Default: 0x1200
  -a, --adapter [edge|cloud]  Choose the adapter to communicate with the
                              gateway. Default: edge
  -d, --devices TEXT          Subset list of device addresses to interact with,
                              separated with ,
  -v, --verbose               Enable verbose mode.
  --no-daemon                 Skip the daemon probe and run an in-process
                              Controller for this invocation (the legacy
                              behavior).
  -V, --version               Show the version and exit.
  -h, --help                  Show this message and exit.

Commands:
  calibrate-lh2  Send LH2 calibration data to the robots.
  flash          Flash a firmware to the robots.
  message        Send a custom text message to the robots.
  monitor        Tail SWARMIT_EVENT_LOG events emitted by bots.
  reset          Reset robots locations.
  start          Start the user application.
  status         Print current status of the robots.
  stop           Stop the user application.
"""


def _make_client():
    """Return a MagicMock pre-wired as a context manager that yields itself.

    The CLI uses `with build_client(...) as client:` everywhere; tests
    patch `swarmit.cli.main.build_client` to return one of these.
    """
    c = MagicMock()
    c.__enter__.return_value = c
    c.__exit__.return_value = None
    return c


def _bootloader_status(*addrs):
    return {
        addr: NodeStatus(
            device=DeviceType.DotBotV3, status=StatusType.Bootloader
        )
        for addr in addrs
    }


def _running_status(*addrs):
    return {
        addr: NodeStatus(device=DeviceType.DotBotV3, status=StatusType.Running)
        for addr in addrs
    }


@pytest.mark.skipif(sys.platform != "linux", reason="Serial port is different")
def test_main_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert result.output == CLI_HELP_EXPECTED


# ---- start / stop / message ----


@patch("swarmit.cli.main.build_client")
def test_start(build_client_mock):
    client = _make_client()
    client.status.return_value = _bootloader_status("1", "2")
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    client.start.assert_called_once()
    client.__exit__.assert_called()


@patch("swarmit.cli.main.build_client")
def test_start_no_device(build_client_mock):
    client = _make_client()
    client.status.return_value = {}
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    assert "No device to start" in result.output
    client.start.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_stop(build_client_mock):
    client = _make_client()
    client.status.return_value = _running_status("1", "2")
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["stop"])
    assert result.exit_code == 0
    client.stop.assert_called_once()


@patch("swarmit.cli.main.build_client")
def test_stop_no_device(build_client_mock):
    client = _make_client()
    client.status.return_value = {}
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "No device to stop" in result.output
    client.stop.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_message(build_client_mock):
    client = _make_client()
    build_client_mock.return_value = client
    runner = CliRunner()
    msg = "Hello swarm"
    result = runner.invoke(main, ["message", msg])
    assert result.exit_code == 0
    client.message.assert_called_with(msg)


# ---- reset ----


@patch("swarmit.cli.main.build_client")
def test_reset(build_client_mock):
    client = _make_client()
    client.status.return_value = _bootloader_status("A", "B")
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["-d", "A,B", "reset", "A:1,2-B:3,4"])
    assert result.exit_code == 0
    client.reset.assert_called_once()


@patch("swarmit.cli.main.build_client")
def test_reset_no_match(build_client_mock):
    client = _make_client()
    client.status.return_value = _bootloader_status("A", "B")
    build_client_mock.return_value = client
    runner = CliRunner()
    # devices say A,B but locations only specify A
    result = runner.invoke(main, ["-d", "A,B", "reset", "A:1,2"])
    assert result.exit_code == 0
    assert "do not match" in result.output
    client.reset.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_reset_no_device_selected(build_client_mock):
    client = _make_client()
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["reset", "A:1,2"])
    assert result.exit_code == 0
    assert "No device selected" in result.output
    client.reset.assert_not_called()
    # No build_client call needed for this short-circuit path
    build_client_mock.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_reset_no_device_ready(build_client_mock):
    client = _make_client()
    client.status.return_value = {}  # no Bootloader devices
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["-d", "A", "reset", "A:1,2"])
    assert result.exit_code == 0
    assert "No device to reset" in result.output
    client.reset.assert_not_called()


# ---- flash ----


@pytest.fixture
def fw(tmp_path):
    fw_path = tmp_path / "fw.bin"
    fw_path.write_bytes(b"firmware")
    return fw_path


def _flash_events(success=True, all_success=True, missed=False):
    """Build a canned client.flash() event sequence."""
    if missed:
        return iter([{"type": "error", "message": "1 OTA start acks missed"}])
    return iter(
        [
            {
                "type": "flash_started",
                "image_size": 8,
                "total_chunks": 1,
                "fw_hash": "DEADBEEF",
                "devices": ["1"],
            },
            {"type": "chunk", "addr": "1", "acked": 1, "total": 1},
            {
                "type": "device_done",
                "addr": "1",
                "success": success,
                "retries": 0,
                "chunks_acked": 1 if success else 0,
                "chunks_total": 1,
            },
            {"type": "complete", "all_success": all_success, "elapsed_s": 0.1},
        ]
    )


@patch("swarmit.cli.main.build_client")
def test_flash_missing_firmware(build_client_mock):
    client = _make_client()
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash"])
    assert result.exit_code == 1
    assert "Missing firmware file" in result.output
    client.flash.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_flash_no_device_ready(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = {}
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)])
    assert result.exit_code == 1
    assert "No ready device found" in result.output
    client.flash.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_flash_user_abort(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = _bootloader_status("1")
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)], input="n\n")
    assert "Do you want to continue?" in result.output
    assert "Abort" in result.output
    assert result.exit_code == 1
    client.flash.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_flash_missing_ota_ack(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = _bootloader_status("1")
    client.flash.return_value = _flash_events(missed=True)
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert "missed" in result.output
    assert result.exit_code == 1
    client.flash.assert_called_once()


@patch("swarmit.cli.main.build_client")
def test_flash_transfer_failed(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = _bootloader_status("1")
    client.flash.return_value = _flash_events(success=False, all_success=False)
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 1
    assert "Transfer failed" in result.output
    client.flash.assert_called_once()
    client.start.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_flash_transfer_success_no_start(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = _bootloader_status("1")
    client.flash.return_value = _flash_events(success=True, all_success=True)
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 0
    client.flash.assert_called_once()
    client.start.assert_not_called()


@patch("swarmit.cli.main.build_client")
def test_flash_transfer_success_with_start(build_client_mock, fw):
    client = _make_client()
    client.status.return_value = _bootloader_status("1")
    client.flash.return_value = _flash_events(success=True, all_success=True)
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(fw), "--start"], input="y\n")
    assert result.exit_code == 0
    client.flash.assert_called_once()
    client.start.assert_called_once()


# ---- monitor ----


@patch("swarmit.cli.main.build_client")
def test_monitor(build_client_mock):
    client = _make_client()
    # Empty iterator → monitor consumes nothing and exits cleanly
    client.watch_log_events.return_value = iter([])
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    client.watch_log_events.assert_called_once()


@patch("swarmit.cli.main.build_client")
def test_monitor_keyboard_interrupt(build_client_mock):
    client = _make_client()

    def _raise():
        raise KeyboardInterrupt
        yield  # unreachable; make this a generator for the for-loop

    client.watch_log_events.return_value = _raise()
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    assert "Stopping monitor" in result.output


# ---- status ----


@patch("swarmit.cli.main.build_client")
def test_status(build_client_mock):
    client = _make_client()
    client.status.return_value = {}
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    client.status.assert_called_once()


@patch("swarmit.cli.main.build_client")
def test_status_watch(build_client_mock):
    client = _make_client()
    client.status.return_value = {}
    client.watch_status.return_value = iter([])  # exits immediately
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["status", "-w"])
    assert result.exit_code == 0
    client.watch_status.assert_called_once()


TEST_CONFIG_TOML = """
adapter = "edge"
serial_port = "/dev/ttyACM0"
baudrate = 1000000
devices = ""
"""


@patch("swarmit.cli.main.build_client")
def test_status_with_config(build_client_mock, tmp_path):
    # Smoke test to verify config file is loaded
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text(TEST_CONFIG_TOML)

    client = _make_client()
    client.status.return_value = {}
    build_client_mock.return_value = client
    runner = CliRunner()
    result = runner.invoke(main, ["-c", str(cfg_path), "status"])
    assert result.exit_code == 0
    client.status.assert_called_once()
