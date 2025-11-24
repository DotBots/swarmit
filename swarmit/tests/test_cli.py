import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from swarmit.cli.main import main
from swarmit.testbed.controller import StartOtaData, TransferDataStatus

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
  -V, --version               Show the version and exit.
  -h, --help                  Show this message and exit.

Commands:
  flash    Flash a firmware to the robots.
  message  Send a custom text message to the robots.
  monitor  Monitor running applications.
  reset    Reset robots locations.
  start    Start the user application.
  status   Print current status of the robots.
  stop     Stop the user application.
"""


@pytest.mark.skipif(sys.platform != "linux", reason="Serial port is different")
def test_main_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert result.output == CLI_HELP_EXPECTED


@patch("swarmit.cli.main.Controller")
def test_start(controller_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    controller_mock().start.assert_called_once()
    controller_mock().terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_stop(controller_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["stop"])
    assert result.exit_code == 0
    controller_mock().stop.assert_called_once()
    controller_mock().terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_reset(controller_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["reset", "1:0.5,0.5"])
    assert result.exit_code == 0
    controller_mock().reset.assert_called_once()
    controller_mock().terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_flash(controller_mock, tmp_path):
    runner = CliRunner()

    # Missing firmware file case
    result = runner.invoke(main, ["flash"])
    assert result.exit_code == 1
    assert "Missing firmware file" in result.output
    controller_mock().start_ota.assert_not_called()
    controller_mock().transfer.assert_not_called()

    # User abort case
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"firmware")
    result = runner.invoke(main, ["flash", str(fw)], input="n\n")
    assert "Do you want to continue?" in result.output
    assert "Abort" in result.output
    assert result.exit_code == 1
    controller_mock().start_ota.assert_not_called()
    controller_mock().transfer.assert_not_called()

    controller_mock().terminate.reset_mock()

    # Missing OTA acknowledgments case
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert "acknowledgments are missing" in result.output
    assert result.exit_code == 1
    controller_mock().start_ota.assert_called_with(fw.read_bytes())
    controller_mock().stop.assert_called_once()
    controller_mock().terminate.assert_called_once()
    controller_mock().transfer.assert_not_called()

    # Transfer failed case
    controller_mock().start_ota.reset_mock()
    controller_mock().stop.reset_mock()
    controller_mock().terminate.reset_mock()
    controller_mock().start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller_mock().transfer.return_value = {
        "1": TransferDataStatus(success=False),
    }
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 1
    controller_mock().start_ota.assert_called_with(fw.read_bytes())
    controller_mock().stop.assert_not_called()
    controller_mock().terminate.assert_called_once()
    controller_mock().transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )

    # Transfer success case without start
    controller_mock().start_ota.reset_mock()
    controller_mock().stop.reset_mock()
    controller_mock().terminate.reset_mock()
    controller_mock().start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller_mock().transfer.return_value = {
        "1": TransferDataStatus(success=True),
    }
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 0
    controller_mock().start_ota.assert_called_with(fw.read_bytes())
    controller_mock().stop.assert_not_called()
    controller_mock().terminate.assert_called_once()
    controller_mock().transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )

    # Transfer success case without start
    controller_mock().start_ota.reset_mock()
    controller_mock().stop.reset_mock()
    controller_mock().terminate.reset_mock()
    controller_mock().start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller_mock().transfer.return_value = {
        "1": TransferDataStatus(success=True),
    }
    result = runner.invoke(main, ["flash", str(fw), "--start"], input="y\n")
    assert result.exit_code == 0
    controller_mock().start_ota.assert_called_with(fw.read_bytes())
    controller_mock().stop.assert_not_called()
    controller_mock().terminate.assert_called_once()
    controller_mock().transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )
    controller_mock().start.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_monitor(controller_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    controller_mock().monitor.assert_called_once()
    controller_mock().terminate.assert_called_once()

    controller_mock().monitor.reset_mock()
    controller_mock().terminate.reset_mock()

    controller_mock().monitor.side_effect = KeyboardInterrupt
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    controller_mock().terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_status(controller_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    controller_mock().status.assert_called_once()
    controller_mock().terminate.assert_called_once()

    controller_mock().status.reset_mock()
    controller_mock().terminate.reset_mock()

    result = runner.invoke(main, ["status", "-w"])
    assert result.exit_code == 0
    controller_mock().status.assert_called_with(True)
    controller_mock().terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_message(controller_mock):
    runner = CliRunner()
    msg = "Hello swarm"
    result = runner.invoke(main, ["message", msg])
    assert result.exit_code == 0
    controller_mock().send_message.assert_called_with(msg)
    controller_mock().terminate.assert_called_once()
