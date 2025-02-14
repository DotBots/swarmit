#!/usr/bin/env python

import logging

import click
import serial
import structlog
from dotbot.serial_interface import SerialInterfaceException, get_default_port
from rich import print
from rich.console import Console

from testbed.swarmit.controller import Controller, ControllerSettings

SERIAL_PORT_DEFAULT = get_default_port()
BAUDRATE_DEFAULT = 1000000


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-p",
    "--port",
    default=SERIAL_PORT_DEFAULT,
    help=f"Serial port to use to send the bitstream to the gateway. Default: {SERIAL_PORT_DEFAULT}.",
)
@click.option(
    "-b",
    "--baudrate",
    default=BAUDRATE_DEFAULT,
    help=f"Serial port baudrate. Default: {BAUDRATE_DEFAULT}.",
)
@click.option(
    "-e",
    "--edge",
    is_flag=True,
    default=False,
    help="Use MQTT adapter to communicate with the edge gateway.",
)
@click.option(
    "-d",
    "--devices",
    type=str,
    default="",
    help="Subset list of devices to interact with, separated with ,",
)
@click.pass_context
def main(ctx, port, baudrate, edge, devices):
    if ctx.invoked_subcommand != "monitor":
        # Disable logging if not monitoring
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                logging.CRITICAL
            ),
        )
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["baudrate"] = baudrate
    ctx.obj["edge"] = edge
    ctx.obj["devices"] = [e[2:] for e in devices.split(",") if e]


@main.command()
@click.pass_context
def start(ctx):
    try:
        settings = ControllerSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=list(ctx.obj["devices"]),
        )
        controller = Controller(settings)
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if controller.ready_devices:
        controller.start()
        print("Application started.")
    else:
        print("No ready devices")
    controller.terminate()


@main.command()
@click.pass_context
def stop(ctx):
    try:
        settings = ControllerSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=list(ctx.obj["devices"]),
        )
        controller = Controller(settings)
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if controller.running_devices:
        controller.stop()
        print("Application stopped.")
    else:
        print("No running devices")
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
@click.argument("firmware", type=click.File(mode="rb"), required=False)
@click.pass_context
def flash(ctx, yes, start, firmware):
    console = Console()
    if firmware is None:
        console.print("[bold red]Error:[/] Missing firmware file. Exiting.")
        ctx.exit()

    fw = bytearray(firmware.read())
    settings = ControllerSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    controller = Controller(settings)
    if not controller.ready_devices:
        console.print("[bold red]Error:[/] No ready devices found. Exiting.")
        controller.terminate()
        return
    print(
        f"Devices to flash ([bold white]{len(controller.ready_devices)}[/bold white]): [[magenta]{', '.join(controller.ready_devices)}[/magenta]]"
    )
    print(f"Image size: [bold cyan]{len(fw)}B[/bold cyan]")
    print("")
    if yes is False:
        click.confirm("Do you want to continue?", default=True, abort=True)

    devices = controller.settings.devices
    ids = controller.start_ota(fw)
    if (devices and sorted(ids) != sorted(devices)) or (
        not devices and sorted(ids) != sorted(controller.ready_devices)
    ):
        console = Console()
        console.print(
            "[bold red]Error:[/] some acknowledgments are missing "
            f'({", ".join(sorted(set(controller.ready_devices).difference(set(ids))))}). '
            "Aborting."
        )
        raise click.Abort()
    try:
        controller.transfer(fw)
    except Exception as exc:
        controller.terminate()
        console = Console()
        console.print(f"[bold red]Error:[/] transfer of image failed: {exc}")
        raise click.Abort()

    if start is True:
        controller.start()
        print("Application started.")
    controller.terminate()


@main.command()
@click.pass_context
def monitor(ctx):
    try:
        settings = ControllerSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=ctx.obj["devices"],
        )
        controller = Controller(settings)
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
    settings = ControllerSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    controller = Controller(settings)
    if not controller.status():
        click.echo("No devices found.")
    controller.terminate()


@main.command()
@click.argument("message", type=str, required=True)
@click.pass_context
def message(ctx, message):
    settings = ControllerSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    controller = Controller(settings)
    controller.send_message(message)
    controller.terminate()


if __name__ == "__main__":
    main(obj={})
