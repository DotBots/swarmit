import sys
from unittest.mock import PropertyMock, patch

import pytest
from click.testing import CliRunner

from swarmit.cli.main import main
from swarmit.testbed.controller import (
    ControllerSettings,
    StartOtaData,
    TransferDataStatus,
)

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
    controller = controller_mock()
    type(controller_mock().return_value).ready_devices = PropertyMock(
        return_value=["1", "2"]
    )
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    assert not result.output.strip()
    controller.start.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_start_no_device(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).ready_devices = PropertyMock(
        return_value=[]
    )
    result = runner.invoke(main, ["start"])
    assert result.exit_code == 0
    assert "No device to start" in result.output
    controller.start.assert_not_called()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_stop(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).running_devices = PropertyMock(
        return_value=["1", "2"]
    )
    result = runner.invoke(main, ["stop"])
    assert result.exit_code == 0
    assert not result.output.strip()
    controller.stop.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_stop_no_device(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).running_devices = PropertyMock(
        return_value=[]
    )
    type(controller_mock.return_value).resetting_devices = PropertyMock(
        return_value=[]
    )
    result = runner.invoke(main, ["stop"])
    assert result.exit_code == 0
    assert "No device to stop" in result.output
    controller.stop.assert_not_called()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_reset(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).settings = PropertyMock(
        return_value=ControllerSettings(devices=[1])
    )
    result = runner.invoke(main, ["reset", "1:0.5,0.5"])
    assert result.exit_code == 0
    controller.reset.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_reset_no_match(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).settings = PropertyMock(
        return_value=ControllerSettings(devices=[1])
    )
    result = runner.invoke(main, ["reset", "2:0.5,0.5"])
    assert result.exit_code == 0
    assert "Selected devices and reset locations do not match" in result.output
    controller.reset.assert_not_called()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_reset_no_device_selected(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).settings = PropertyMock(
        return_value=ControllerSettings(devices=[])
    )
    result = runner.invoke(main, ["reset", "1:0.5,0.5"])
    assert result.exit_code == 0
    assert "No device selected" in result.output
    controller.reset.assert_not_called()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_reset_no_device_ready(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).settings = PropertyMock(
        return_value=ControllerSettings(devices=[1])
    )
    type(controller_mock.return_value).ready_devices = PropertyMock(
        return_value=[]
    )
    result = runner.invoke(main, ["reset", "1:0.5,0.5"])
    assert result.exit_code == 0
    assert "No device to reset" in result.output
    controller.reset.assert_not_called()
    controller.terminate.assert_called_once()


@pytest.fixture
def fw(tmp_path):
    fw_path = tmp_path / "fw.bin"
    fw_path.write_bytes(b"firmware")
    return fw_path


@patch("swarmit.cli.main.Controller")
def test_flash_missing_firmware(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["flash"])
    assert result.exit_code == 1
    assert "Missing firmware file" in result.output
    controller.start_ota.assert_not_called()
    controller.transfer.assert_not_called()


@patch("swarmit.cli.main.Controller")
def test_flash_no_device_ready(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    type(controller_mock.return_value).ready_devices = PropertyMock(
        return_value=[]
    )
    result = runner.invoke(main, ["flash", str(fw)])
    assert result.exit_code == 1
    assert "No ready device found. Exiting" in result.output
    controller.start_ota.assert_not_called()
    controller.transfer.assert_not_called()


@patch("swarmit.cli.main.Controller")
def test_flash_user_abort(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["flash", str(fw)], input="n\n")
    assert "Do you want to continue?" in result.output
    assert "Abort" in result.output
    assert result.exit_code == 1
    controller.start_ota.assert_not_called()
    controller.transfer.assert_not_called()


@patch("swarmit.cli.main.Controller")
def test_flash_missing_ota_ack(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert "acknowledgments are missing" in result.output
    assert result.exit_code == 1
    controller.start_ota.assert_called_with(fw.read_bytes())
    controller.stop.assert_called_once()
    controller.terminate.assert_called_once()
    controller.transfer.assert_not_called()


@patch("swarmit.cli.main.Controller")
def test_flash_transfer_failed(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    controller.start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller.transfer.return_value = {
        "1": TransferDataStatus(success=False),
    }
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 1
    controller.start_ota.assert_called_with(fw.read_bytes())
    controller.stop.assert_not_called()
    controller.terminate.assert_called_once()
    controller.transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )


@patch("swarmit.cli.main.Controller")
def test_flash_transfer_success_no_start(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    controller.start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller.transfer.return_value = {
        "1": TransferDataStatus(success=True),
    }
    result = runner.invoke(main, ["flash", str(fw)], input="y\n")
    assert result.exit_code == 0
    controller.start_ota.assert_called_with(fw.read_bytes())
    controller.stop.assert_not_called()
    controller.terminate.assert_called_once()
    controller.transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )


@patch("swarmit.cli.main.Controller")
def test_flash_transfer_success_with_start(controller_mock, fw):
    runner = CliRunner()
    controller = controller_mock()
    controller.start_ota.return_value = {
        "missed": [],
        "acked": ["1"],
        "ota": StartOtaData(),
    }
    controller.transfer.return_value = {
        "1": TransferDataStatus(success=True),
    }
    result = runner.invoke(main, ["flash", str(fw), "--start"], input="y\n")
    assert result.exit_code == 0
    controller.start_ota.assert_called_with(fw.read_bytes())
    controller.stop.assert_not_called()
    controller.terminate.assert_called_once()
    controller.transfer.assert_called_with(
        fw.read_bytes(), controller_mock().start_ota.return_value["acked"]
    )
    controller.start.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_monitor(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    controller.monitor.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_monitor_keyboard_interrupt(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    controller.monitor.side_effect = KeyboardInterrupt
    result = runner.invoke(main, ["monitor"])
    assert result.exit_code == 0
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_status(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    controller.status.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_status_watch(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["status", "-w"])
    assert result.exit_code == 0
    controller.status.assert_called_with(watch=True)
    controller.terminate.assert_called_once()


TEST_CONFIG_TOML = """
adapter = "edge"
serial_port = "/dev/ttyACM0"
baudrate = 1000000
devices = ""
"""


@patch("swarmit.cli.main.Controller")
def test_status_with_config(controller_mock, tmp_path):
    # Smoke test to verify config file is loaded
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text(TEST_CONFIG_TOML)

    runner = CliRunner()
    controller = controller_mock()
    result = runner.invoke(main, ["-c", str(cfg_path), "status"])
    assert result.exit_code == 0
    controller.status.assert_called_once()
    controller.terminate.assert_called_once()


@patch("swarmit.cli.main.Controller")
def test_message(controller_mock):
    runner = CliRunner()
    controller = controller_mock()
    msg = "Hello swarm"
    result = runner.invoke(main, ["message", msg])
    assert result.exit_code == 0
    controller.send_message.assert_called_with(msg)
    controller.terminate.assert_called_once()
