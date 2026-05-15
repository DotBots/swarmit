#!/usr/bin/env python
"""Entry point for `swarmit-daemon`.

Runs the swarmit FastAPI backend without mounting the React frontend.
Binds to 127.0.0.1 by default. The CLI probes this daemon on startup
and routes commands through it when it's reachable.
"""

import click
import uvicorn

from swarmit import __version__
from swarmit.cli.main import DEFAULTS
from swarmit.testbed.controller import ControllerSettings
from swarmit.testbed.helpers import load_toml_config
from swarmit.testbed.webserver import api, init_api

DEFAULTS_DAEMON = {
    **DEFAULTS,
    "http_port": 8001,
    "bind_host": "127.0.0.1",
}


@click.command()
@click.option(
    "-c",
    "--config-path",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a .toml configuration file.",
)
@click.option(
    "-p",
    "--port",
    type=str,
    help=f"Serial port for the gateway. Default: {DEFAULTS_DAEMON['serial_port']}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS_DAEMON['baudrate']}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    help=f"MQTT host. Default: {DEFAULTS_DAEMON['mqtt_host']}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    help=f"MQTT port. Default: {DEFAULTS_DAEMON['mqtt_port']}.",
)
@click.option(
    "-T",
    "--mqtt-use_tls",
    is_flag=True,
    help="Use TLS with MQTT.",
)
@click.option(
    "-n",
    "--network-id",
    type=str,
    help=f"Marilib network ID. Default: 0x{DEFAULTS_DAEMON['swarmit_network_id']}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    help=f"Gateway adapter. Default: {DEFAULTS_DAEMON['adapter']}",
)
@click.option(
    "-d",
    "--devices",
    type=str,
    default="",
    help="Subset list of device addresses, separated with ,",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose mode.",
)
@click.option(
    "--bind-host",
    type=str,
    help=f"HTTP bind address. Default: {DEFAULTS_DAEMON['bind_host']} (localhost-only).",
)
@click.option(
    "--http-port",
    type=int,
    help=f"HTTP port. Default: {DEFAULTS_DAEMON['http_port']}.",
)
@click.version_option(
    __version__, "-V", "--version", prog_name="swarmit-daemon"
)
def main(
    config_path,
    port,
    baudrate,
    mqtt_host,
    mqtt_port,
    mqtt_use_tls,
    network_id,
    adapter,
    devices,
    verbose,
    bind_host,
    http_port,
):
    """Run the swarmit daemon (FastAPI backend, no UI)."""
    config_data = load_toml_config(config_path)
    cli_args = {
        "adapter": adapter,
        "serial_port": port,
        "baudrate": baudrate,
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_use_tls": mqtt_use_tls,
        "swarmit_network_id": network_id,
        "devices": devices,
        "verbose": verbose,
        "bind_host": bind_host,
        "http_port": http_port,
    }
    final_config = {
        **DEFAULTS_DAEMON,
        **{k: v for k, v in config_data.items() if v is not None},
        **{k: v for k, v in cli_args.items() if v not in (None, False)},
    }

    # Daemon currently always runs with auth disabled. Refuse to bind to
    # anything other than localhost so a stray --bind-host 0.0.0.0 (or
    # any LAN-reachable address) cannot accidentally expose unauthenticated
    # /flash, /start, /stop, /reset, /lh2_calibration, /message endpoints.
    # Cross-machine deployment with JWT auth is planned for Phase D.
    SAFE_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}
    if final_config["bind_host"] not in SAFE_BIND_HOSTS:
        click.echo(
            f"refusing to start: --bind-host={final_config['bind_host']!r} "
            f"would expose unauthenticated control endpoints. "
            f"Allowed: {sorted(SAFE_BIND_HOSTS)}.",
            err=True,
        )
        raise click.Abort()

    settings = ControllerSettings(
        serial_port=final_config["serial_port"],
        serial_baudrate=final_config["baudrate"],
        mqtt_host=final_config["mqtt_host"],
        mqtt_port=final_config["mqtt_port"],
        mqtt_use_tls=final_config["mqtt_use_tls"],
        network_id=int(final_config["swarmit_network_id"], 16),
        adapter=final_config["adapter"],
        devices=[d for d in final_config["devices"].split(",") if d],
        verbose=final_config["verbose"],
    )

    init_api(api, settings, auth_mode="none")
    uvicorn.run(
        api,
        host=final_config["bind_host"],
        port=final_config["http_port"],
        log_level="info",
    )


if __name__ == "__main__":
    main()  # pragma: no cover
