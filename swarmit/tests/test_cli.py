import sys

import pytest
from click.testing import CliRunner

from swarmit.cli.main import main

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
