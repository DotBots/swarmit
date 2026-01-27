"""Test module for the main function."""

import asyncio
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from swarmit.dashboard.main import main
from swarmit.testbed.controller import ControllerSettings
from swarmit.tests.utils import MarilibSerialAdapterMock

MAIN_HELP_EXPECTED = """Usage: main [OPTIONS]

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
  -m, --map-size TEXT         Size of the map on the ground in mm, in the format
                              WIDTHxHEIGHT. Default: 2500x2500.
  -v, --verbose               Enable verbose mode.
  --open-browser              Open the dashboard in a web browser automatically.
  --http-port INTEGER         HTTP port. Default: edge
  -V, --version               Show the version and exit.
  --help                      Show this message and exit.
"""


@pytest.fixture
def controller_mock(monkeypatch, tmp_path, capsys):

    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.webserver.API_DB_URL",
        f"sqlite:///{tmp_path}/database.db",
    )
    monkeypatch.setattr("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)

    class ControllerSettingsMock(ControllerSettings):
        adapter_wait_timeout: float = 0.1
        adapter: str = "edge"
        network_id: int = 999

    monkeypatch.setattr(
        "swarmit.testbed.webserver.ControllerSettings", ControllerSettingsMock
    )

    yield


@pytest.fixture
def open_browser_mock(monkeypatch):
    monkeypatch.setattr("webbrowser.open", time.sleep(0.3))


@pytest.mark.skipif(sys.platform != "linux", reason="Serial port is different")
def test_dashboard_main_help(controller_mock, open_browser_mock):
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert result.output == MAIN_HELP_EXPECTED


@patch("uvicorn.Server.serve", new_callable=AsyncMock)
def test_dashboard_main(serve, controller_mock, open_browser_mock):

    serve.return_value = time.sleep(0.2)
    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    serve.assert_awaited()


@patch("uvicorn.Server.serve", new_callable=AsyncMock)
def test_dashboard_main_raise_exception(
    serve, controller_mock, open_browser_mock
):
    runner = CliRunner()
    serve.side_effect = Exception("Test exception")
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "Web server error: Test exception" in result.output


@patch("uvicorn.Server.serve")
def test_dashboard_main_server_canceled(
    serve, controller_mock, open_browser_mock
):
    serve.side_effect = asyncio.exceptions.CancelledError
    runner = CliRunner()
    result = runner.invoke(main)
    assert result.exit_code == 0
    assert "Web server cancelled" in result.output


@patch("webbrowser.open")
def test_dashboard_main_webbrowser(
    webbrowser_open, controller_mock, open_browser_mock
):
    webbrowser_open.side_effect = SystemExit()
    runner = CliRunner()
    result = runner.invoke(main, ["--open-browser"])
    assert result.exit_code == 0
    webbrowser_open.assert_called_with("http://localhost:8001")
