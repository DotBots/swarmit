#!/usr/bin/env python
import asyncio
import logging
import tomllib
import webbrowser

import click
import structlog
import uvicorn

from testbed.cli.main import DEFAULTS
from testbed.swarmit import __version__
from testbed.swarmit.controller import ControllerSettings
from testbed.swarmit.webserver import api, init_api, mount_frontend


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
    help=f"Serial port to use to send the bitstream to the gateway. Default: {DEFAULTS["serial_port"]}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS["baudrate"]}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    help=f"MQTT host. Default: {DEFAULTS["mqtt_host"]}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    help=f"MQTT port. Default: {DEFAULTS["mqtt_port"]}.",
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
    help=f"Marilib network ID to use. Default: 0x{DEFAULTS["swarmit_network_id"]}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    help=f"Choose the adapter to communicate with the gateway. Default: {DEFAULTS["adapter"]}",
)
@click.option(
    "-d",
    "--devices",
    type=str,
    default="",
    help="Subset list of device addresses to interact with, separated with ,",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose mode.",
)
@click.option(
    "--open-browser/--no-open-browser",
    default=True,
    help="Open the dashboard in a web browser automatically.",
)
@click.version_option(__version__, "-V", "--version", prog_name="swarmit")
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
        "verbose": verbose,
    }

    # Merge in order of priority: CLI > config > defaults
    final_config = {
        **DEFAULTS,
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
        verbose=final_config["verbose"],
    )

    asyncio.run(async_web(controller_settings, open_browser))

async def async_web(settings: ControllerSettings, open_browser: bool):
    tasks = []
    try:
        tasks.append(
            asyncio.create_task(
                name="Web server",
                coro=_serve_fast_api(settings),
            )
        )

        if open_browser:
            tasks.append(
                asyncio.create_task(
                    name="Web browser",
                    coro=_open_webbrowser(settings.mqtt_port),
                )
            )

        await asyncio.gather(*tasks)

    except Exception as exc:  # TODO: use the right exception here
        print(f"Error: {exc}")
    except SystemExit:
        pass
    finally:
        print("Stopping controller")
        for task in tasks:
            print(f"Cancelling task '{task.get_name()}'")
            task.cancel()
        print("Controller stopped")


async def _serve_fast_api(settings: ControllerSettings):
    """Starts the web server application."""
    init_api(api, settings)
    mount_frontend(api)
    config = uvicorn.Config(api, port=settings.mqtt_port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    except asyncio.exceptions.CancelledError:
        print("Web server cancelled")
    else:
        raise SystemExit()


async def _open_webbrowser(http_port: int):
    """Wait until the server is ready before opening a web browser."""
    while 1:
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


def load_toml_config(path):
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


if __name__ == "__main__":
    main(obj={})
