#!/usr/bin/env python

import logging
import time

import click
import serial
import structlog
from dotbot.serial_interface import SerialInterfaceException, get_default_port
from rich.console import Console

from testbed.swarmit.experiment import Experiment, ExperimentSettings

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
    ctx.obj["devices"] = [e for e in devices.split(",") if e]


@main.command()
@click.pass_context
def start(ctx):
    try:
        settings = ExperimentSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=list(ctx.obj["devices"]),
        )
        experiment = Experiment(settings)
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if experiment.ready_devices:
        experiment.start()
        print("Experiment started.")
    else:
        print("No ready devices")
    experiment.terminate()


@main.command()
@click.pass_context
def stop(ctx):
    try:
        settings = ExperimentSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=list(ctx.obj["devices"]),
        )
        experiment = Experiment(settings)
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return
    if experiment.running_devices:
        experiment.stop()
        print("Experiment stopped.")
    else:
        print("No running devices")
    experiment.terminate()


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
    settings = ExperimentSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    experiment = Experiment(settings)
    if not experiment.ready_devices:
        console.print("[bold red]Error:[/] No ready devices found. Exiting.")
        experiment.terminate()
        return
    start_time = time.time()
    print(f"Image size: {len(fw)}B")
    print("")
    if yes is False:
        click.confirm("Do you want to continue?", default=True, abort=True)

    devices = experiment.settings.devices
    ids = experiment.start_ota(fw)
    if (devices and sorted(ids) != sorted(devices)) or (
        not devices and sorted(ids) != sorted(experiment.ready_devices)
    ):
        console = Console()
        console.print(
            "[bold red]Error:[/] some acknowledgments are missing "
            f'({", ".join(sorted(set(experiment.ready_devices).difference(set(ids))))}). '
            "Aborting."
        )
        raise click.Abort()
    try:
        experiment.transfer(fw)
    except Exception as exc:
        experiment.terminate()
        console = Console()
        console.print(f"[bold red]Error:[/] transfer of image failed: {exc}")
        raise click.Abort()
    finally:
        print(f"Elapsed: {time.time() - start_time:.3f}s")

    if start is True:
        experiment.start()
        print("Experiment started.")
    experiment.terminate()


@main.command()
@click.pass_context
def monitor(ctx):
    try:
        settings = ExperimentSettings(
            serial_port=ctx.obj["port"],
            serial_baudrate=ctx.obj["baudrate"],
            mqtt_host="argus.paris.inria.fr",
            mqtt_port=8883,
            edge=ctx.obj["edge"],
            devices=ctx.obj["devices"],
        )
        experiment = Experiment(settings)
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        console = Console()
        console.print(f"[bold red]Error:[/] {exc}")
        return {}
    try:
        experiment.monitor()
    except KeyboardInterrupt:
        print("Stopping monitor.")
    finally:
        experiment.terminate()


@main.command()
@click.pass_context
def status(ctx):
    settings = ExperimentSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    experiment = Experiment(settings)
    if not experiment.status():
        click.echo("No devices found.")
    experiment.terminate()


@main.command()
@click.argument("message", type=str, required=True)
@click.pass_context
def message(ctx, message):
    settings = ExperimentSettings(
        serial_port=ctx.obj["port"],
        serial_baudrate=ctx.obj["baudrate"],
        mqtt_host="argus.paris.inria.fr",
        mqtt_port=8883,
        edge=ctx.obj["edge"],
        devices=ctx.obj["devices"],
    )
    experiment = Experiment(settings)
    experiment.send_message(message)
    experiment.terminate()


if __name__ == "__main__":
    main(obj={})
