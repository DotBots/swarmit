#!/usr/bin/env python

import threading
import time

import click
from dotbot_utils.serial_interface import (
    get_default_port,
)
from rich import print
from rich.console import Console
from rich.live import Live
from rich.pretty import pprint
from tqdm import tqdm

from swarmit import __version__
from swarmit.client import build_client
from swarmit.testbed.controller import (
    CHUNK_SIZE,
    OTA_ACK_TIMEOUT_DEFAULT,
    OTA_MAX_RETRIES_DEFAULT,
    ControllerSettings,
    NodeStatus,
    ResetLocation,
    generate_status,
)
from swarmit.testbed.helpers import load_toml_config
from swarmit.testbed.logger import setup_logging
from swarmit.testbed.protocol import StatusType


def _print_log_event(event: dict) -> None:
    """Render one SWARMIT_EVENT_LOG event for the CLI's monitor view."""
    addr = event.get("addr", "?")
    ts = event.get("timestamp", 0)
    data_hex = event.get("data_hex", "")
    # Most LOG payloads are text — try utf-8, fall back to <hex:...> for
    # opaque binary blobs.
    try:
        data_repr = bytes.fromhex(data_hex).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        data_repr = f"<hex:{data_hex}>"
    print(f"[magenta]{addr}[/] [dim]t={ts}[/] {data_repr}")


def _render_transfer_summary(device_results: list[dict], console) -> None:
    """Render per-device flash outcomes in a wrap-friendly grid.

    Each cell is one device: `ADDR acked/total r:N ✓|✗`. Rich's
    Columns auto-wraps cells side-by-side based on terminal width,
    so 100+ devices stay readable without 100 rows of vertical
    space. Failures (if any) are also listed separately at the
    tail so a quick scan of the bottom of the screen surfaces them
    even when the grid is dense.
    """
    from rich.columns import Columns
    from rich.text import Text

    if not device_results:
        return

    cells = []
    failures = []
    for d in sorted(device_results, key=lambda r: r["addr"]):
        success = d.get("success", False)
        color = "green" if success else "red"
        marker = "✓" if success else "✗"
        acked = d.get("chunks_acked", 0)
        total = d.get("chunks_total", 0)
        retries = d.get("retries", 0)
        cells.append(
            Text.from_markup(
                f"[magenta]{d['addr']}[/] "
                f"[{color}]{acked}/{total} r:{retries} {marker}[/]"
            )
        )
        if not success:
            failures.append((d["addr"], acked, total, retries))

    succ = sum(1 for d in device_results if d.get("success"))
    console.print()
    console.print(
        f"[bold]Transfer status[/] "
        f"([green]{succ}[/]/{len(device_results)} ok):"
    )
    console.print(Columns(cells, padding=(0, 2), expand=False))

    if failures:
        console.print()
        console.print(f"[bold red]Failures[/] ({len(failures)}):")
        for addr, acked, total, retries in failures:
            console.print(
                f"  [red]✗[/] [magenta]{addr}[/] "
                f"[red]{acked}/{total}[/] r:{retries}"
            )


def _live_run(client, op, settings, message: str) -> None:
    """Run a blocking client op (`start`/`stop`) in a thread while a
    Rich Live table consumes status snapshots from `client.watch_status()`.

    In daemon mode `watch_status` is the `/events` SSE stream (one
    long-lived HTTP connection, no per-tick `GET /status` spam). In
    local mode it reads in-process `status_data` on the same cadence.

    Effect: the user sees the device table from the current state
    onward (e.g. starting in Bootloader, transitioning to Running)
    instead of staring at a blank terminal until the op returns.
    """
    err: list[BaseException] = []
    done = threading.Event()

    def _runner():
        try:
            op()
        except BaseException as e:
            err.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_runner)
    t.start()

    # Empty initial render is replaced on the first snapshot; daemon's
    # /events emits the first status event within ~tens of ms.
    with Live(
        generate_status({}, settings.devices, message),
        refresh_per_second=4,
    ) as live:
        for snapshot in client.watch_status():
            live.update(generate_status(snapshot, settings.devices, message))
            if done.is_set():
                break
    print()

    t.join()
    if err:
        raise err[0]


def _filter_by_status(
    status_map: dict[str, NodeStatus],
    devices_filter: list[str],
    *target_statuses: StatusType,
) -> list[str]:
    """Return the device addresses in `status_map` matching any of
    `target_statuses` and (if `devices_filter` is non-empty) appearing
    in `devices_filter`.
    """
    filter_set = set(devices_filter) if devices_filter else None
    return [
        addr
        for addr, node in status_map.items()
        if node.status in target_statuses
        and (filter_set is None or addr in filter_set)
    ]


DEFAULTS = {
    "adapter": "edge",
    "serial_port": get_default_port(),
    "baudrate": 1000000,
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    # Default network ID for SwarmIT tests is 0x12**
    # See https://crystalfree.atlassian.net/wiki/spaces/Mari/pages/3324903426/Registry+of+Mari+Network+IDs
    "swarmit_network_id": "1200",
    "mqtt_use_tls": False,
    "verbose": False,
}


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
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
    help=f"Serial port to use to send the bitstream to the gateway. Default: {DEFAULTS['serial_port']}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS['baudrate']}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    help=f"MQTT host. Default: {DEFAULTS['mqtt_host']}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    help=f"MQTT port. Default: {DEFAULTS['mqtt_port']}.",
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
    help=f"Marilib network ID to use. Default: 0x{DEFAULTS['swarmit_network_id']}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    help=f"Choose the adapter to communicate with the gateway. Default: {DEFAULTS['adapter']}",
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
    "--no-server",
    is_flag=True,
    help="Skip the swarmit-server probe and run an in-process Controller "
    "for this invocation (the legacy behavior).",
)
@click.version_option(__version__, "-V", "--version", prog_name="swarmit")
@click.pass_context
def main(
    ctx,
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
    no_server,
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

    setup_logging()
    ctx.ensure_object(dict)
    ctx.obj["no_server"] = no_server
    ctx.obj["settings"] = ControllerSettings(
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


@main.command()
@click.pass_context
def start(ctx):
    """Start the user application."""
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        ready = _filter_by_status(
            client.status(), settings.devices, StatusType.Bootloader
        )
        if not ready:
            print("No device to start")
            return
        devices = settings.devices if settings.devices else None
        _live_run(
            client, lambda: client.start(devices=devices), settings, "to start"
        )


@main.command()
@click.pass_context
def stop(ctx):
    """Stop the user application."""
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        stoppable = _filter_by_status(
            client.status(),
            settings.devices,
            StatusType.Running,
            StatusType.Programming,
            StatusType.Resetting,
        )
        if not stoppable:
            print("[bold]No device to stop[/]")
            return
        devices = settings.devices if settings.devices else None
        _live_run(
            client, lambda: client.stop(devices=devices), settings, "to stop"
        )


@main.command()
@click.argument(
    "locations",
    type=str,
)
@click.pass_context
def reset(ctx, locations):
    """Reset robots locations.

    Locations are provided as '<device_addr>:<x>,<y>-<device_addr>:<x>,<y>|...'
    """
    settings = ctx.obj["settings"]
    devices = settings.devices
    print(devices)
    if not devices:
        print("No device selected.")
        return
    # Keys are uppercase hex strings (matching settings.devices and
    # everything else in the codebase) — Controller.reset indexes by
    # string address, not int.
    parsed_locations = {
        location.split(":")[0].upper(): ResetLocation(
            pos_x=int(float(location.split(":")[1].split(",")[0])),
            pos_y=int(float(location.split(":")[1].split(",")[1])),
        )
        for location in locations.split("-")
    }
    if sorted(devices) != sorted(parsed_locations.keys()):
        print("Selected devices and reset locations do not match.")
        return
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        ready = _filter_by_status(
            client.status(), settings.devices, StatusType.Bootloader
        )
        if not ready:
            print("No device to reset.")
            return
        client.reset(parsed_locations)


@main.command()
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Flash the firmware without prompt.",
)
@click.option(
    "-s",
    "--start",
    is_flag=True,
    help="Start the firmware once flashed.",
)
@click.option(
    "-t",
    "--ota-timeout",
    type=float,
    default=OTA_ACK_TIMEOUT_DEFAULT,
    show_default=True,
    help="Timeout in seconds for each OTA ACK message.",
)
@click.option(
    "-r",
    "--ota-max-retries",
    type=int,
    default=OTA_MAX_RETRIES_DEFAULT,
    show_default=True,
    help="Number of retries for each OTA message (start or chunk) transfer.",
)
@click.argument("firmware", type=click.File(mode="rb"), required=False)
@click.pass_context
def flash(ctx, yes, start, ota_timeout, ota_max_retries, firmware):
    """Flash a firmware to the robots.

    Streams per-chunk progress via the daemon's /flash/stream SSE
    endpoint when a daemon is reachable, or via in-process polling of
    the controller's transfer_data otherwise. CLI rendering is the same
    either way. `--ota-timeout` and `--ota-max-retries` are sent as
    per-flash overrides in both modes.
    """
    console = Console()
    if firmware is None:
        console.print("[bold red]Error:[/] Missing firmware file. Exiting.")
        raise click.Abort()

    settings = ctx.obj["settings"]
    fw = firmware.read()

    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        ready = _filter_by_status(
            client.status(), settings.devices, StatusType.Bootloader
        )
        if not ready:
            console.print(
                "[bold red]Error:[/] No ready device found. Exiting."
            )
            raise click.Abort()

        print(f"Devices to flash ([bold white]{len(ready)}):[/]")
        pprint(ready, expand_all=True)
        if not yes:
            click.confirm("Do you want to continue?", default=True, abort=True)

        events = client.flash(
            fw,
            devices=settings.devices if settings.devices else None,
            ota_timeout=ota_timeout,
            ota_max_retries=ota_max_retries,
        )
        progress = None
        per_device_acked: dict[str, int] = {}
        device_results: list[dict] = []
        try:
            for ev in events:
                etype = ev.get("type")
                if etype == "flash_started":
                    print()
                    print(f"Image size: [bold cyan]{ev['image_size']}B[/]")
                    print(f"Image hash: [bold cyan]{ev['fw_hash']}[/]")
                    print(
                        f"Radio chunks ([bold]{CHUNK_SIZE}B[/bold]): "
                        f"{ev['total_chunks']}"
                    )
                    progress = tqdm(
                        total=ev["total_chunks"] * len(ev["devices"]),
                        unit="chunk",
                        unit_scale=False,
                        colour="green",
                        ncols=100,
                    )
                    progress.set_description(
                        f"Flashing {len(ev['devices'])} bot(s)"
                    )
                elif etype == "chunk":
                    if progress is None:
                        continue
                    prev = per_device_acked.get(ev["addr"], 0)
                    progress.update(ev["acked"] - prev)
                    per_device_acked[ev["addr"]] = ev["acked"]
                elif etype == "device_done":
                    device_results.append(ev)
                elif etype == "complete":
                    if progress is not None:
                        progress.close()
                    print(f"Elapsed: [bold cyan]{ev['elapsed_s']:.3f}s[/]")
                    _render_transfer_summary(device_results, console)
                    if not ev.get("all_success", False):
                        console.print("[bold red]Error:[/] Transfer failed.")
                        raise click.Abort()
                    if start:
                        time.sleep(1)
                        client.start(
                            devices=(
                                settings.devices if settings.devices else None
                            )
                        )
                    return
                elif etype == "error":
                    if progress is not None:
                        progress.close()
                    console.print(
                        f"[bold red]Error:[/] {ev.get('message', 'unknown')}"
                    )
                    raise click.Abort()
        except KeyboardInterrupt:
            if progress is not None:
                progress.close()
            console.print("[bold yellow]Aborted by user.[/]")
            raise click.Abort()


@main.command()
@click.pass_context
def monitor(ctx):
    """Tail SWARMIT_EVENT_LOG events emitted by bots.

    Different from `status -w`: that one renders the device table;
    this one prints LOG events as bots send them. Routes through the
    unified client — daemon mode streams via the /events SSE feed,
    --no-server builds an in-process Controller.
    """
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        try:
            for event in client.watch_log_events():
                _print_log_event(event)
        except KeyboardInterrupt:
            print("Stopping monitor.")


@main.command()
@click.option(
    "-w",
    "--watch",
    is_flag=True,
    help="Keep watching the testbed status.",
)
@click.pass_context
def status(ctx, watch):
    """Print current status of the robots."""
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        if watch:
            from rich.live import Live

            with Live(
                generate_status(client.status(), settings.devices),
                refresh_per_second=4,
            ) as live:
                try:
                    for snapshot in client.watch_status(interval=0.25):
                        live.update(
                            generate_status(snapshot, settings.devices)
                        )
                except KeyboardInterrupt:
                    pass
        else:
            print(generate_status(client.status(), settings.devices))
            print()


@main.command()
@click.argument("message", type=str, required=True)
@click.pass_context
def message(ctx, message):
    """Send a custom text message to the robots."""
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        client.message(message)


@main.command()
@click.argument(
    "lh2-calibration-file", type=click.File(mode="rb"), required=True
)
@click.pass_context
def calibrate_lh2(ctx, lh2_calibration_file):
    """Send LH2 calibration data to the robots."""
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        client.send_lh2_calibration(lh2_calibration_file.read())


if __name__ == "__main__":
    main(obj={})  # pragma: no cover
