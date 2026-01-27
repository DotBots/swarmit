#!/usr/bin/env python

import time

import click
from dotbot_utils.serial_interface import (
    get_default_port,
)
from rich import print
from rich.console import Console
from rich.pretty import pprint

from swarmit import __version__
from swarmit.testbed.controller import (
    CHUNK_SIZE,
    OTA_ACK_TIMEOUT_DEFAULT,
    OTA_MAX_RETRIES_DEFAULT,
    Controller,
    ControllerSettings,
    ResetLocation,
    print_transfer_status,
)
from swarmit.testbed.helpers import load_toml_config
from swarmit.testbed.logger import setup_logging

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
    controller = Controller(ctx.obj["settings"])
    if controller.ready_devices:
        controller.start()
    else:
        print("No device to start")
    controller.terminate()


@main.command()
@click.pass_context
def stop(ctx):
    """Stop the user application."""
    controller = Controller(ctx.obj["settings"])
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
    controller = Controller(ctx.obj["settings"])
    devices = controller.settings.devices
    print(devices)
    if not devices:
        print("No device selected.")
        controller.terminate()
        return
    locations = {
        int(location.split(":")[0], 16): ResetLocation(
            pos_x=int(float(location.split(":")[1].split(",")[0])),
            pos_y=int(float(location.split(":")[1].split(",")[1])),
        )
        for location in locations.split("-")
    }
    if sorted(devices) and sorted(locations.keys()) != sorted(devices):
        print("Selected devices and reset locations do not match.")
        controller.terminate()
        return
    if not controller.ready_devices:
        print("No device to reset.")
        controller.terminate()
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
    """Flash a firmware to the robots."""
    console = Console()
    if firmware is None:
        console.print("[bold red]Error:[/] Missing firmware file. Exiting.")
        raise click.Abort()

    ctx.obj["settings"].ota_timeout = ota_timeout
    ctx.obj["settings"].ota_max_retries = ota_max_retries
    fw = bytearray(firmware.read())
    controller = Controller(ctx.obj["settings"])
    if not controller.ready_devices:
        console.print("[bold red]Error:[/] No ready device found. Exiting.")
        controller.terminate()
        raise click.Abort()

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
            f"[bold red]Error:[/] {len(start_data['missed'])} acknowledgments "
            f"are missing ({', '.join(sorted(set(start_data['missed'])))}). "
            "Aborting."
        )
        controller.stop()
        controller.terminate()
        raise click.Abort()

    print()
    print(f"Image size: [bold cyan]{len(fw)}B[/]")
    print(
        f"Image hash: [bold cyan]{start_data['ota'].fw_hash.hex().upper()}[/]"
    )
    print(
        f"Radio chunks ([bold]{CHUNK_SIZE}B[/bold]): {start_data['ota'].chunks}"
    )
    start_time = time.time()
    data = controller.transfer(fw, start_data["acked"])
    print(f"Elapsed: [bold cyan]{time.time() - start_time:.3f}s[/bold cyan]")
    print_transfer_status(data, start_data["ota"])
    if controller.settings.verbose:
        print("\n[b]Transfer data:[/]")
        pprint(data, indent_guides=False, expand_all=True)
    if all([device.success for device in data.values()]) is False:
        controller.terminate()
        console = Console()
        console.print("[bold red]Error:[/] Transfer failed.")
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
        controller.monitor()
    except KeyboardInterrupt:
        print("Stopping monitor.")
    finally:
        controller.terminate()


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
    controller = Controller(ctx.obj["settings"])
    controller.status(watch=watch)
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
    main(obj={})  # pragma: no cover
