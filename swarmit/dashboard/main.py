#!/usr/bin/env python
import asyncio
import webbrowser

import click
import uvicorn

from swarmit import __version__
from swarmit.cli.main import DEFAULTS
from swarmit.testbed.controller import ControllerSettings
from swarmit.testbed.helpers import load_toml_config
from swarmit.testbed.webserver import api, init_api, mount_frontend

DEFAULTS_DASHBOARD = {
    **DEFAULTS,
    "http_port": 8001,
    "map_size": "2500x2500",
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
    help=f"Serial port to use to send the bitstream to the gateway. Default: {DEFAULTS_DASHBOARD['serial_port']}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS_DASHBOARD['baudrate']}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    help=f"MQTT host. Default: {DEFAULTS_DASHBOARD['mqtt_host']}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    help=f"MQTT port. Default: {DEFAULTS_DASHBOARD['mqtt_port']}.",
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
    help=f"Marilib network ID to use. Default: 0x{DEFAULTS_DASHBOARD['swarmit_network_id']}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    help=f"Choose the adapter to communicate with the gateway. Default: {DEFAULTS_DASHBOARD['adapter']}",
)
@click.option(
    "-d",
    "--devices",
    type=str,
    default="",
    help="Subset list of device addresses to interact with, separated with ,",
)
@click.option(
    "-m",
    "--map-size",
    type=str,
    default=DEFAULTS_DASHBOARD['map_size'],
    help="Size of the map on the ground in mm, in the format WIDTHxHEIGHT. Default: 2500x2500.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose mode.",
)
@click.option(
    "--open-browser",
    is_flag=True,
    help="Open the dashboard in a web browser automatically.",
)
@click.option(
    "--http-port",
    type=int,
    help=f"HTTP port. Default: {DEFAULTS_DASHBOARD['adapter']}",
)
@click.version_option(__version__, "-V", "--version", prog_name="swarmit")
def main(
    config_path,
    port,
    baudrate,
    http_port,
    mqtt_host,
    mqtt_port,
    mqtt_use_tls,
    network_id,
    adapter,
    devices,
    map_size,
    verbose,
    open_browser,
):
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
        "map_size": map_size,
        "verbose": verbose,
        "http_port": http_port,
    }

    # Merge in order of priority: CLI > config > defaults
    final_config = {
        **DEFAULTS_DASHBOARD,
        **{k: v for k, v in config_data.items() if v is not None},
        **{k: v for k, v in cli_args.items() if v not in (None, False)},
    }

    controller_settings = ControllerSettings(
        serial_port=final_config["serial_port"],
        serial_baudrate=final_config["baudrate"],
        mqtt_host=final_config["mqtt_host"],
        mqtt_port=final_config["mqtt_port"],
        mqtt_use_tls=final_config["mqtt_use_tls"],
        network_id=int(final_config["swarmit_network_id"], 16),
        adapter=final_config["adapter"],
        devices=[d for d in final_config["devices"].split(",") if d],
        map_size=final_config["map_size"],
        verbose=final_config["verbose"],
    )

    asyncio.run(
        async_web(controller_settings, final_config["http_port"], open_browser)
    )


async def async_web(
    settings: ControllerSettings, http_port: int, open_browser: bool
):
    tasks = []
    try:

        tasks.append(
            asyncio.create_task(
                name="Web server",
                coro=_serve_fast_api(settings, http_port),
            )
        )

        if open_browser:
            tasks.append(
                asyncio.create_task(
                    name="Web browser",
                    coro=_open_webbrowser(http_port),
                )
            )

        await asyncio.gather(*tasks)

    except Exception as exc:  # TODO: use the right exception here
        print(f"Error: {exc}")
    except SystemExit:
        print("Exiting...")
    finally:
        print("Stopping controller")
        for task in tasks:
            print(f"Cancelling task '{task.get_name()}'")
            task.cancel()
        print("Controller stopped")


async def _serve_fast_api(settings: ControllerSettings, http_port: int):
    """Starts the web server application."""
    init_api(api, settings)
    mount_frontend(api)
    config = uvicorn.Config(
        api, host="0.0.0.0", port=http_port, log_level="info"
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    except asyncio.exceptions.CancelledError:
        print("Web server cancelled")
    except Exception as e:
        print(f"Web server error: {e}")
        raise
    else:
        raise SystemExit()


async def _open_webbrowser(http_port: int):
    """Wait until the server is ready before opening a web browser."""
    while True:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", http_port)
        except ConnectionRefusedError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            break

    url = f"http://localhost:{http_port}"
    print(f"Opening webbrowser: {url}")
    webbrowser.open(url)


if __name__ == "__main__":
    main(obj={})  # pragma: no cover
