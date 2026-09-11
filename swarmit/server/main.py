#!/usr/bin/env python
"""Entry point for `swarmit-server`.

Two deployment intents, one binary:

- Local-dev convenience:  `swarmit-server --local`
  Binds 127.0.0.1, auth off, DB off. The local CLI auto-discovers it at
  localhost:8001 and routes commands through it instead of building a
  fresh in-process Controller per invocation.

- Shared service:         `swarmit-server`
  Binds 0.0.0.0, JWT required, JWT records DB on. Used on a testbed
  server reachable by operators and remote CLIs.

`--bind-host` overrides the default for either mode. The safety guard
refuses to combine `--local` (auth off) with anything other than a
localhost bind.
"""

import asyncio
import webbrowser

import click
import uvicorn

from swarmit import __version__
from swarmit.cli.main import DEFAULTS
from swarmit.testbed.controller import ControllerSettings
from swarmit.testbed.helpers import load_toml_config
from swarmit.testbed.webserver import api, init_api, mount_frontend

DEFAULTS_SERVER = {
    **DEFAULTS,
    "http_port": 8001,
    "bounds": ["0,0,2000,2000"],
}


def parse_bounds(specs):
    """Turn `x,y,w,h` strings into the rectangles the dashboard draws.

    A bounds is a view of the frame and carries no calibration, so it takes
    four numbers and nothing is inferred from them.
    """
    specs = list(specs) or DEFAULTS_SERVER["bounds"]
    rectangles = []
    for spec in specs:
        parts = [part.strip() for part in str(spec).split(",")]
        if len(parts) != 4:
            raise click.BadParameter(
                f"bounds {spec!r}: four numbers, x,y,w,h in mm"
            )
        try:
            rectangles.append([int(part) for part in parts])
        except ValueError as exc:
            raise click.BadParameter(
                f"bounds {spec!r}: x,y,w,h must be whole millimetres"
            ) from exc
    return rectangles

# Bind hosts allowed in `--local` mode (auth disabled).
SAFE_BIND_HOSTS = {"127.0.0.1", "localhost", "::1"}


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
    help=f"Serial port for the gateway. Default: {DEFAULTS_SERVER['serial_port']}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS_SERVER['baudrate']}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    help=f"MQTT host. Default: {DEFAULTS_SERVER['mqtt_host']}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    help=f"MQTT port. Default: {DEFAULTS_SERVER['mqtt_port']}.",
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
    help=f"Marilib network ID. Default: 0x{DEFAULTS_SERVER['swarmit_network_id']}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    help=f"Gateway adapter. Default: {DEFAULTS_SERVER['adapter']}",
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
    "--local",
    is_flag=True,
    help=(
        "Local-only preset: bind 127.0.0.1, disable JWT auth, skip the "
        "JWT records DB. Use this for local-dev convenience so the CLI "
        "auto-discovers a fast in-process backend."
    ),
)
@click.option(
    "--bind-host",
    type=str,
    help=(
        "HTTP bind address. Default: 0.0.0.0 (or 127.0.0.1 with --local). "
        "Refused for non-localhost when --local is set."
    ),
)
@click.option(
    "--http-port",
    type=int,
    help=f"HTTP port. Default: {DEFAULTS_SERVER['http_port']}.",
)
@click.option(
    "--bounds",
    "bounds",
    type=str,
    multiple=True,
    help=(
        "The rectangle of the frame the dashboard draws and clips to, as "
        "x,y,w,h in mm. Repeat for a set. Default: 0,0,2000,2000."
    ),
)
@click.option(
    "--open-browser",
    is_flag=True,
    help="Open the dashboard in a web browser automatically.",
)
@click.version_option(
    __version__, "-V", "--version", prog_name="swarmit-server"
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
    local,
    bind_host,
    http_port,
    bounds,
    open_browser,
):
    """Run the swarmit FastAPI backend."""
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
        "bounds": list(bounds) or None,
    }
    final_config = {
        **DEFAULTS_SERVER,
        **{k: v for k, v in config_data.items() if v is not None},
        **{k: v for k, v in cli_args.items() if v not in (None, False)},
    }

    settings = ControllerSettings(
        serial_port=final_config["serial_port"],
        serial_baudrate=final_config["baudrate"],
        mqtt_host=final_config["mqtt_host"],
        mqtt_port=final_config["mqtt_port"],
        mqtt_use_tls=final_config["mqtt_use_tls"],
        network_id=int(final_config["swarmit_network_id"], 16),
        adapter=final_config["adapter"],
        devices=[d for d in final_config["devices"].split(",") if d],
        bounds=parse_bounds(final_config["bounds"]),
        verbose=final_config["verbose"],
    )

    run_server(
        settings,
        local=local,
        bind_host=final_config.get("bind_host"),
        http_port=final_config["http_port"],
        open_browser=open_browser,
    )


def run_server(
    settings: ControllerSettings,
    *,
    local: bool,
    bind_host: str | None,
    http_port: int,
    open_browser: bool,
) -> None:
    """Start the swarmit FastAPI backend with the given settings."""
    auth_mode = "none" if local else "jwt"
    default_bind = "127.0.0.1" if local else "0.0.0.0"
    bind = bind_host or default_bind

    if auth_mode == "none" and bind not in SAFE_BIND_HOSTS:
        click.echo(
            f"refusing to start: --bind-host={bind!r} with --local would "
            f"expose unauthenticated control endpoints. "
            f"Allowed with --local: {sorted(SAFE_BIND_HOSTS)}.",
            err=True,
        )
        raise click.Abort()

    init_api(api, settings, auth_mode=auth_mode)
    mount_frontend(api)

    asyncio.run(_serve(bind, http_port, open_browser))


async def _serve(bind: str, http_port: int, open_browser: bool):
    tasks = [
        asyncio.create_task(_run_uvicorn(bind, http_port), name="Web server"),
    ]
    if open_browser:
        tasks.append(
            asyncio.create_task(
                _open_webbrowser(http_port), name="Web browser"
            )
        )
    try:
        await asyncio.gather(*tasks)
    except SystemExit:
        pass
    finally:
        for t in tasks:
            t.cancel()


async def _run_uvicorn(bind: str, http_port: int):
    config = uvicorn.Config(api, host=bind, port=http_port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except asyncio.exceptions.CancelledError:
        pass


async def _open_webbrowser(http_port: int):
    """Open the dashboard URL once uvicorn is actually accepting connections."""
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
    main()  # pragma: no cover
