#!/usr/bin/env python

import logging
import time

import click
import serial
import structlog
from dotbot.serial_interface import SerialInterfaceException, get_default_port
from rich import print
from rich.console import Console
from rich.pretty import pprint

from testbed.swarmit import __version__
from testbed.swarmit.controller import (
    CHUNK_SIZE,
    OTA_CHUNK_MAX_RETRIES_DEFAULT,
    OTA_CHUNK_TIMEOUT_DEFAULT,
    Controller,
    ControllerSettings,
    ResetLocation,
    print_transfer_status,
)

SERIAL_PORT_DEFAULT = get_default_port()
BAUDRATE_DEFAULT = 1000000
MQTT_HOST_DEFAULT = "localhost"
MQTT_PORT_DEFAULT = 1883
# Default network ID for SwarmIT tests is 0x12**
# See https://crystalfree.atlassian.net/wiki/spaces/Mari/pages/3324903426/Registry+of+Mari+Network+IDs
SWARMIT_NETWORK_ID_DEFAULT = "1200"


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-p",
    "--port",
    type=str,
    default=SERIAL_PORT_DEFAULT,
    help=f"Serial port to use to send the bitstream to the gateway. Default: {SERIAL_PORT_DEFAULT}.",
)
@click.option(
    "-b",
    "--baudrate",
    type=int,
    default=BAUDRATE_DEFAULT,
    help=f"Serial port baudrate. Default: {BAUDRATE_DEFAULT}.",
)
@click.option(
    "-H",
    "--mqtt-host",
    type=str,
    default=MQTT_HOST_DEFAULT,
    help=f"MQTT host. Default: {MQTT_HOST_DEFAULT}.",
)
@click.option(
    "-P",
    "--mqtt-port",
    type=int,
    default=MQTT_PORT_DEFAULT,
    help=f"MQTT port. Default: {MQTT_PORT_DEFAULT}.",
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
    default=SWARMIT_NETWORK_ID_DEFAULT,
    help=f"Marilib network ID to use. Default: 0x{SWARMIT_NETWORK_ID_DEFAULT}",
)
@click.option(
    "-a",
    "--adapter",
    type=click.Choice(["edge", "cloud"], case_sensitive=True),
    default="edge",
    show_default=True,
    help="Choose the adapter to communicate with the gateway.",
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
def main(
    ctx,
    port,
    baudrate,
    mqtt_host,
    mqtt_port,
    mqtt_use_tls,
    network_id,
    adapter,
    devices,
    verbose,
):
    if ctx.invoked_subcommand != "monitor":
        # Disable logging if not monitoring
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                logging.CRITICAL
            ),
        )
    ctx.ensure_object(dict)
    ctx.obj["settings"] = ControllerSettings(
        serial_port=port,
        serial_baudrate=baudrate,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_use_tls=mqtt_use_tls,
        network_id=int(network_id, 16),
        adapter=adapter,
        devices=[d for d in devices.split(",") if d],
        verbose=verbose,
    )


@main.command()
@click.pass_context
def start(ctx):
    """Start the user application."""
    try:
        controller = Controller(ctx.obj["settings"])
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if controller.ready_devices:
        controller.start()
    else:
        print("No device to start")
    controller.terminate()


@main.command()
@click.pass_context
def stop(ctx):
    """Stop the user application."""
    try:
        controller = Controller(ctx.obj["settings"])
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if controller.running_devices or controller.resetting_devices:
        controller.stop()
    else:
        print("[bold]No device to stop[/]")
    controller.terminate()


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
    try:
        controller = Controller(ctx.obj["settings"])
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return

    devices = controller.settings.devices
    if not devices:
        print("No devices selected.")
        return
    locations = {
        int(location.split(":")[0], 16): ResetLocation(
            pos_x=int(float(location.split(":")[1].split(",")[0]) * 1e6),
            pos_y=int(float(location.split(":")[1].split(",")[1]) * 1e6),
        )
        for location in locations.split("-")
    }
    if sorted(devices) and sorted(locations.keys()) != sorted(devices):
        print("Selected devices and reset locations do not match.")
        return
    if not controller.ready_devices:
        print("No device to reset.")
        return
    controller.reset(locations)
    controller.terminate()


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
    "--chunk-timeout",
    type=float,
    default=OTA_CHUNK_TIMEOUT_DEFAULT,
    show_default=True,
    help="Timeout for each chunk transfer in seconds.",
)
@click.option(
    "-r",
    "--chunk-retries",
    type=int,
    default=OTA_CHUNK_MAX_RETRIES_DEFAULT,
    show_default=True,
    help="Number of retries for each chunk transfer.",
)
@click.argument("firmware", type=click.File(mode="rb"), required=False)
@click.pass_context
def flash(ctx, yes, start, chunk_timeout, chunk_retries, firmware):
    """Flash a firmware to the robots."""
    console = Console()
    if firmware is None:
        console.print("[bold red]Error:[/] Missing firmware file. Exiting.")
        ctx.exit()

    fw = bytearray(firmware.read())
    controller = Controller(ctx.obj["settings"])
    if not controller.ready_devices:
        console.print("[bold red]Error:[/] No ready devices found. Exiting.")
        controller.terminate()
        return
    print(
        f"Devices to flash ([bold white]{len(controller.ready_devices)}):[/]"
    )
    pprint(controller.ready_devices, expand_all=True)
    if yes is False:
        click.confirm("Do you want to continue?", default=True, abort=True)

    start_data = controller.start_ota(fw)
    if controller.settings.verbose:
        print("\n[b]Start OTA response:[/]")
        pprint(start_data, indent_guides=False, expand_all=True)
    if start_data["missed"]:
        console = Console()
        console.print(
            "[bold red]Error:[/] some acknowledgments are missing "
            f"({', '.join(sorted(set(start_data["missed"])))}). "
            "Aborting."
        )
        controller.stop()
        controller.terminate()
        raise click.Abort()
    print()
    print(f"Image size: [bold cyan]{len(fw)}B[/]")
    print(
        f"Image hash: [bold cyan]{start_data["ota"].fw_hash.hex().upper()}[/]"
    )
    print(
        f"Radio chunks ([bold]{CHUNK_SIZE}B[/bold]): {start_data["ota"].chunks}"
    )
    start_time = time.time()
    data = controller.transfer(
        fw, start_data["acked"], timeout=chunk_timeout, retries=chunk_retries
    )
    print(f"Elapsed: [bold cyan]{time.time() - start_time:.3f}s[/bold cyan]")
    print_transfer_status(data, start_data["ota"])
    if controller.settings.verbose:
        print("\n[b]Transfer data:[/]")
        pprint(data, indent_guides=False, expand_all=True)
    if not all([value.hashes_match for value in data.values()]):
        controller.terminate()
        console = Console()
        console.print("[bold red]Error:[/] Hashes do not match.")
        raise click.Abort()

    if start is True:
        time.sleep(1)
        controller.start()
    controller.terminate()


@main.command()
@click.pass_context
def monitor(ctx):
    """Monitor running applications."""
    try:
        controller = Controller(ctx.obj["settings"])
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return {}
    try:
        controller.monitor()
    except KeyboardInterrupt:
        print("Stopping monitor.")
    finally:
        controller.terminate()


@main.command()
@click.pass_context
def status(ctx):
    """Print current status of the robots."""
    controller = Controller(ctx.obj["settings"])
    controller.status()
    controller.terminate()


@main.command()
@click.argument("message", type=str, required=True)
@click.pass_context
def message(ctx, message):
    """Send a custom text message to the robots."""
    controller = Controller(ctx.obj["settings"])
    controller.send_message(message)
    controller.terminate()


if __name__ == "__main__":
    main(obj={})
