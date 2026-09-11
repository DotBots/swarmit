#!/usr/bin/env python

import os
import threading
import time
from pathlib import Path

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
from swarmit.testbed.adapter import (
    DEVICE_CHUNK_RATE_HZ,
    OTA_DOWNLINK_UTILIZATION,
)
from swarmit.testbed.controller import (
    CHUNK_SIZE,
    OTA_ACK_TIMEOUT_DEFAULT,
    OTA_MAX_RETRIES_DEFAULT,
    ControllerSettings,
    NodeStatus,
    ResetLocation,
    generate_info,
    generate_status,
)
from swarmit.testbed.helpers import (
    load_toml_config,
    read_calibration,
    read_lh2_calibration_payload,
    reference_points,
)
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
    # OTA pacing. The transfer paces itself from the schedule the gateway
    # reports; these scale that derivation. 0 means "derive it".
    "ota_utilization": OTA_DOWNLINK_UTILIZATION,
    "ota_device_chunk_rate": DEVICE_CHUNK_RATE_HZ,
    "ota_report_timeout": 0,
    "verbose": False,
}


def _conn_to_config(conn, swarm_id):
    """Translate `--conn` + `--swarm-id` into config overrides.

    One discriminated connection string — `mqtts://host:port` (broker) or
    a serial device path (gateway). swarmit has no simulator. The internal
    `adapter` enum stays an implementation detail. Broker credentials come
    from `DOTBOT_MQTT_USER` / `DOTBOT_MQTT_PASS` in the environment.

    Returns a dict of config keys (only the ones the connection sets), or
    `{}` if `conn` is None (fall through to defaults / config file).
    Raises `click.ClickException` on a malformed conn / missing swarm-id.
    """
    if conn is None:
        return {}
    lowered = conn.strip().lower()
    if lowered in ("simulator", "sim"):
        raise click.ClickException(
            "swarmit has no simulator connection; use a serial gateway "
            "(/dev/ttyACM0) or a broker (mqtts://host:port)."
        )
    if lowered.startswith(("mqtt://", "mqtts://")):
        from marilib.communication_adapter import parse_mqtt_url

        # marilib owns the URL→parts mapping (host/port/tls + default
        # port) so swarmit, dotbot controller, and MQTTAdapter.from_url
        # can't drift. Userinfo creds are discarded — broker auth comes
        # from DOTBOT_MQTT_USER / DOTBOT_MQTT_PASS in the environment.
        host, port, use_tls, _user, _pass = parse_mqtt_url(conn)
        if not host:
            raise click.ClickException(
                f"no host in connection string: {conn!r}"
            )
        if not swarm_id:
            raise click.ClickException(
                f"--conn {conn} needs --swarm-id: the broker carries multiple "
                "swarms; --swarm-id selects yours."
            )
        cfg = {
            "adapter": "cloud",
            "mqtt_host": host,
            "mqtt_port": port,
            "mqtt_use_tls": use_tls,
            "mqtt_username": os.environ.get("DOTBOT_MQTT_USER"),
            "mqtt_password": os.environ.get("DOTBOT_MQTT_PASS"),
        }
        if swarm_id:
            cfg["swarmit_network_id"] = swarm_id
        return cfg
    if "://" in conn:
        raise click.ClickException(
            f"unrecognized connection scheme in {conn!r} "
            "(expected mqtt(s):// or a device path)."
        )
    # serial device path
    cfg = {"adapter": "edge", "serial_port": conn}
    if swarm_id:
        cfg["swarmit_network_id"] = swarm_id
    return cfg


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-c",
    "--config-path",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a .toml configuration file.",
)
@click.option(
    "-n",
    "--conn",
    "--connection",
    "conn",
    type=str,
    help=(
        "Connection to the swarm — one discriminated string: an MQTT "
        "broker `mqtts://host:port`, or a serial gateway `/dev/ttyACM0`."
    ),
)
@click.option(
    "-s",
    "--swarm-id",
    "swarm_id",
    type=str,
    help=(
        "Swarm id in hex. Required for an mqtt connection (the broker "
        "carries many swarms); ignored for a serial gateway."
    ),
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    help=f"Serial port baudrate. Default: {DEFAULTS['baudrate']}.",
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
    conn,
    swarm_id,
    baudrate,
    devices,
    verbose,
    no_server,
):
    config_data = load_toml_config(config_path)

    # `conn` / `swarm_id` may come from the CLI or the config file (CLI wins).
    conn = conn if conn is not None else config_data.get("conn")
    swarm_id = (
        swarm_id if swarm_id is not None else config_data.get("swarm_id")
    )
    conn_config = _conn_to_config(conn, swarm_id)

    cli_args = {
        "baudrate": baudrate,
        "devices": devices,
        "verbose": verbose,
    }

    # Merge in order of priority: CLI > conn translation > config > defaults.
    # `conn` / `swarm_id` config-file keys are consumed by _conn_to_config,
    # so drop them from the raw config merge.
    raw_config = {
        k: v
        for k, v in config_data.items()
        if k not in ("conn", "swarm_id") and v is not None
    }
    final_config = {
        **DEFAULTS,
        **raw_config,
        **conn_config,
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
        mqtt_username=final_config.get("mqtt_username"),
        mqtt_password=final_config.get("mqtt_password"),
        network_id=int(final_config["swarmit_network_id"], 16),
        adapter=final_config["adapter"],
        devices=[d for d in final_config["devices"].split(",") if d],
        ota_utilization=float(final_config["ota_utilization"]),
        ota_device_chunk_rate=float(final_config["ota_device_chunk_rate"]),
        ota_report_timeout=float(final_config["ota_report_timeout"]),
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
@click.option(
    "--image-version",
    default="",
    help=(
        "Version label to store with the image and show in status/info, "
        'e.g. "0.9.0-12-g1a2b3c4". Display only - bots are compared by '
        "image digest, so leaving this empty costs only readability. "
        "Distinct from --fw-version, which selects a released platform "
        "artifact to flash."
    ),
)
@click.argument("firmware", type=click.File(mode="rb"), required=False)
@click.pass_context
def flash(
    ctx, yes, start, ota_timeout, ota_max_retries, image_version, firmware
):
    """Flash a firmware to the robots.

    Streams per-chunk progress via the daemon's /flash/stream SSE
    endpoint when a daemon is reachable, or via in-process polling of
    the controller's transfer_data otherwise. CLI rendering is the same
    either way. `--ota-timeout` and `--ota-max-retries` are sent as
    per-flash overrides in both modes.

    The image is labelled with the firmware's filename and, if given,
    `--image-version`. Bots report both back, so `swarm status` can show
    which image each one is running.
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
            # The filename is the name an operator already thinks in, so it
            # is the default label rather than something to be typed twice.
            image_name=Path(getattr(firmware, "name", "")).name,
            image_version=image_version,
        )
        progress = None
        per_device_acked: dict[str, int] = {}
        device_results: list[dict] = []
        n_blocks = 0
        block_size = 1
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
                    n_blocks = ev.get("n_blocks", 0)
                    block_size = ev.get("block_size", 1) or 1
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
                    if n_blocks and per_device_acked:
                        # Blocks fully delivered to the slowest bot, so the
                        # indicator only advances once every bot has the block.
                        done_blocks = (
                            min(per_device_acked.values()) // block_size
                        )
                        progress.set_postfix_str(
                            f"blk {min(done_blocks, n_blocks)}/{n_blocks}"
                        )
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
                elif etype == "warning":
                    # Printed rather than raised: the flash continues without
                    # the devices named here, and the operator has to see which.
                    console.print(
                        f"[bold yellow]Warning:[/] {ev.get('message', '')}"
                    )
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
@click.option(
    "--raw",
    is_flag=True,
    help=(
        "Also dump the wire bytes of the status frame and the device-info "
        "reply, offset-prefixed. Offsets match the field tables in "
        "doc/wire-protocol.md."
    ),
)
@click.pass_context
def info(ctx, raw):
    """Show full detail for the selected device(s).

    Everything from the status packet plus the raw crash report (decoded
    reset reason, fault status registers, and faulting PC/LR), and what the
    device reports it is running: image, sandbox firmware versions,
    calibration and uptime. Scope it with the group's -d/--devices option,
    e.g. `swarm -d <addr> info`; with no -d it shows every known device.
    """
    settings = ctx.obj["settings"]
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        # Ask rather than wait for the background sweep: `info` is the
        # command an operator runs precisely when they want it now.
        client.refresh_device_info(settings.devices or None)
        print(generate_info(client.status(), settings.devices, show_raw=raw))


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
    "lh2-calibration-file",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
)
@click.pass_context
def calibrate_lh2(ctx, lh2_calibration_file):
    """Send LH2 calibration data to the robots.

    Takes a schema 2 calibration TOML; the wire payload is built from its
    [[station]].homography tables at send time.
    """
    console = Console()
    settings = ctx.obj["settings"]
    try:
        blob = read_lh2_calibration_payload(lh2_calibration_file)
        # The dashboard draws its crosses at the placements' points, which
        # only an in-process controller sees from here.
        settings.reference_points = reference_points(
            read_calibration(lh2_calibration_file)
        )
    except ValueError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        raise click.Abort()
    if not blob:
        console.print("[bold red]Error:[/] Calibration file is empty.")
        raise click.Abort()

    # Format: 1-byte count + N x 36B matrices. Read the count client-side so
    # there is visible output in daemon mode too — over HTTP the controller's
    # own progress prints run in the server process, not this terminal.
    homography_count = blob[0]
    console.print(
        f"Sending [bold cyan]{homography_count}[/] calibration "
        f"matrix/matrices ([bold]{len(blob)}B[/]) to the swarm..."
    )
    with build_client(settings, no_server=ctx.obj["no_server"]) as client:
        try:
            with console.status(
                "[bold green]Sending calibration...",
                spinner="dots",
            ):
                client.send_lh2_calibration(blob)
        except (ValueError, RuntimeError) as exc:
            # ValueError: local Controller validation. RuntimeError: daemon
            # returned 400 (same validation, surfaced over HTTP).
            console.print(f"[bold red]Error:[/] {exc}")
            raise click.Abort()
    console.print("[bold green]✓[/] Calibration sent.")


@main.command()
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
    default=8001,
    help="HTTP port. Default: 8001.",
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
@click.pass_context
def serve(
    ctx,
    local,
    bind_host,
    http_port,
    bounds,
    open_browser,
):
    """Start the swarmit FastAPI backend."""
    from swarmit.server.main import parse_bounds, run_server

    settings = ctx.obj["settings"]
    settings.bounds = parse_bounds(bounds)
    run_server(
        settings,
        local=local,
        bind_host=bind_host,
        http_port=http_port,
        open_browser=open_browser,
    )


if __name__ == "__main__":
    main(obj={})  # pragma: no cover
