#!/usr/bin/env python

import base64
import time

import click
import httpx
from rich import print
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text
from tqdm import tqdm

from swarmit import __version__
from swarmit.testbed.logger import setup_logging
from swarmit.testbed.protocol import StatusType

DEFAULTS = {
    "api_url": "http://localhost:8001",
    "verbose": False,
}


def _auth_headers(ctx):
    token = ctx.obj.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _battery_color(level: int) -> str:
    if level > 2900:
        return "cyan"
    if level > 1500:
        return "green"
    return "red"


def generate_status_from_dict(data: dict, devices=[], status_message="found"):
    """Generate a Rich renderable from the /status JSON response dict."""
    filtered = {
        addr: info
        for addr, info in data.items()
        if (devices and addr in devices) or (not devices)
    }
    if not filtered:
        return Group(Text(f"\nNo device {status_message}\n"))

    header = Text(
        f"\n{len(filtered)} device{'s' if len(filtered) > 1 else ''} {status_message}\n"
    )
    table = Table()
    table.add_column("Device Addr", style="magenta", no_wrap=True)
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Battery", style="cyan", justify="center")
    table.add_column("Position", style="cyan", justify="center")
    table.add_column(
        "Status",
        style="green",
        justify="center",
        width=max(len(m) for m in StatusType.__members__),
    )
    for addr, info in sorted(filtered.items()):
        status_name = info.get("status", "")
        device_name = info.get("device", "")
        battery = info.get("battery", 0)
        pos_x = info.get("pos_x", 0)
        pos_y = info.get("pos_y", 0)
        color = "[bold cyan]" if status_name == "Running" else "[bold green]"
        table.add_row(
            addr,
            device_name,
            f"[{_battery_color(battery)}]{battery / 1000:.2f}V"
            f" ({int(battery / 3000 * 100)}%)",
            f"({pos_x}, {pos_y})",
            f"{color}{status_name}",
        )
    return Group(header, table)


def _live_status(url, devices, timeout=5.0, message="found"):
    """Poll /status and display a live Rich table for *timeout* seconds."""
    deadline = time.time() + timeout
    try:
        with Live(refresh_per_second=4) as live:
            while time.time() < deadline:
                resp = httpx.get(f"{url}/status")
                if resp.status_code == 200:
                    data = resp.json().get("response", {})
                    live.update(
                        generate_status_from_dict(data, devices, message)
                    )
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-c",
    "--config-path",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a .toml configuration file.",
)
@click.option(
    "--api-url",
    type=str,
    default=DEFAULTS["api_url"],
    show_default=True,
    help="Base URL of the SwarmIT dashboard REST API.",
)
@click.option(
    "--token",
    type=str,
    default=None,
    envvar="SWARMIT_TOKEN",
    help="JWT authentication token. Also readable from SWARMIT_TOKEN env var.",
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
@click.version_option(__version__, "-V", "--version", prog_name="swarmit")
@click.pass_context
def main(ctx, config_path, api_url, token, devices, verbose):
    setup_logging()
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url
    ctx.obj["token"] = token
    ctx.obj["devices"] = [d for d in devices.split(",") if d]
    ctx.obj["verbose"] = verbose


@main.command()
@click.pass_context
def start(ctx):
    """Start the user application."""
    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]
    resp = httpx.post(
        f"{url}/start",
        json={"devices": devices or None},
        headers=_auth_headers(ctx),
    )
    resp.raise_for_status()
    _live_status(url, devices, timeout=5.0, message="to start")


@main.command()
@click.pass_context
def stop(ctx):
    """Stop the user application."""
    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]
    resp = httpx.post(
        f"{url}/stop",
        json={"devices": devices or None},
        headers=_auth_headers(ctx),
    )
    resp.raise_for_status()
    _live_status(url, devices, timeout=5.0, message="to stop")


@main.command()
@click.argument("locations", type=str)
@click.pass_context
def reset(ctx, locations):
    """Reset robots locations.

    Locations are provided as '<device_addr>:<x>,<y>-<device_addr>:<x>,<y>|...'
    """
    url = ctx.obj["api_url"]
    parsed = {}
    for entry in locations.split("-"):
        addr, coords = entry.split(":")
        x_str, y_str = coords.split(",")
        parsed[addr] = {
            "pos_x": int(float(x_str)),
            "pos_y": int(float(y_str)),
        }
    resp = httpx.post(
        f"{url}/reset",
        json={"locations": parsed},
        headers=_auth_headers(ctx),
    )
    resp.raise_for_status()
    print(resp.json())


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
    "start_after",
    is_flag=True,
    help="Start the firmware once flashed.",
)
@click.argument("firmware", type=click.File(mode="rb"), required=False)
@click.pass_context
def flash(ctx, yes, start_after, firmware):
    """Flash a firmware to the robots."""
    console = Console()
    if firmware is None:
        console.print("[bold red]Error:[/] Missing firmware file. Exiting.")
        raise click.Abort()

    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]
    fw_b64 = base64.b64encode(firmware.read()).decode()

    if not yes:
        click.confirm("Do you want to continue?", default=True, abort=True)

    # Step 1 – initiate OTA start (non-blocking)
    resp = httpx.post(
        f"{url}/ota/start",
        json={"firmware_b64": fw_b64, "devices": devices or None},
        headers=_auth_headers(ctx),
    )
    if resp.status_code != 200:
        console.print(
            f"[bold red]Error:[/] {resp.json().get('detail', resp.text)}"
        )
        raise click.Abort()

    # Step 2 – poll /ota/start/status until negotiation completes
    while True:
        status_resp = httpx.get(
            f"{url}/ota/start/status", headers=_auth_headers(ctx)
        )
        status_resp.raise_for_status()
        start_data = status_resp.json()
        if start_data["status"] == "done":
            break
        time.sleep(0.25)

    acked = start_data["acked"]
    missed = start_data.get("missed", [])
    total_chunks = start_data["total_chunks"]
    fw_hash = start_data["fw_hash"]

    console.print(
        f"Image hash: [bold cyan]{fw_hash}[/]"
        f"  chunks: [bold]{total_chunks}[/]"
        f"  acked: [bold green]{len(acked)}[/]"
        + (f"  [bold red]missed: {', '.join(missed)}[/]" if missed else "")
    )

    if missed:
        console.print(
            f"[bold red]Error:[/] {len(missed)} acknowledgment(s) missing "
            f"({', '.join(sorted(missed))}). Aborting."
        )
        raise click.Abort()

    # Step 3 – start background chunk transfer
    resp = httpx.post(
        f"{url}/ota/transfer",
        json={"devices": acked},
        headers=_auth_headers(ctx),
    )
    if resp.status_code == 409:
        console.print("[bold red]Error:[/] OTA transfer already in progress.")
        raise click.Abort()
    if resp.status_code != 200:
        console.print(
            f"[bold red]Error:[/] {resp.json().get('detail', resp.text)}"
        )
        raise click.Abort()

    # Step 4 – poll transfer progress with a tqdm bar
    pbar = None
    last_n = 0

    while True:
        prog_resp = httpx.get(
            f"{url}/ota/transfer/status", headers=_auth_headers(ctx)
        )
        prog_resp.raise_for_status()
        prog = prog_resp.json()
        ota_status = prog["status"]

        if pbar is None and prog["total_chunks"] > 0:
            pbar = tqdm(
                total=prog["total_chunks"],
                unit="chunk",
                colour="green",
                ncols=100,
            )
            pbar.set_description("Flashing firmware")

        if pbar is not None and prog["devices"]:
            min_acked = min(
                d["chunks_acked"] for d in prog["devices"].values()
            )
            if min_acked > last_n:
                pbar.update(min_acked - last_n)
                last_n = min_acked

        if ota_status == "success":
            if pbar:
                pbar.close()
            console.print("[bold green]Flash successful.[/]")
            break
        if ota_status == "failed":
            if pbar:
                pbar.close()
            console.print(
                f"[bold red]Error:[/] Flash failed: {prog.get('error')}"
            )
            raise click.Abort()

        time.sleep(0.5)

    if start_after:
        resp = httpx.post(
            f"{url}/start",
            json={"devices": devices or None},
            headers=_auth_headers(ctx),
        )
        resp.raise_for_status()


@main.command()
@click.pass_context
def monitor(ctx):
    """Monitor running applications."""
    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]
    try:
        with Live(refresh_per_second=4) as live:
            while True:
                resp = httpx.get(f"{url}/status")
                if resp.status_code == 200:
                    data = resp.json().get("response", {})
                    live.update(
                        generate_status_from_dict(data, devices, "found")
                    )
                time.sleep(0.25)
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
    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]

    def _fetch():
        resp = httpx.get(f"{url}/status")
        resp.raise_for_status()
        return generate_status_from_dict(
            resp.json().get("response", {}), devices, "found"
        )

    if not watch:
        print(_fetch())
        return

    try:
        with Live(refresh_per_second=4) as live:
            while True:
                live.update(_fetch())
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass


@main.command()
@click.argument("message", type=str, required=True)
@click.pass_context
def message(ctx, message):
    """Send a custom text message to the robots."""
    url = ctx.obj["api_url"]
    devices = ctx.obj["devices"]
    resp = httpx.post(
        f"{url}/message",
        json={"message": message, "devices": devices or None},
        headers=_auth_headers(ctx),
    )
    resp.raise_for_status()
    print(resp.json())


if __name__ == "__main__":
    main(obj={})  # pragma: no cover
