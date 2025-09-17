"""Module containing the swarmit controller class."""

import dataclasses
import time
from binascii import hexlify
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from dotbot.logger import LOGGER
from dotbot.protocol import Packet, Payload
from dotbot.serial_interface import get_default_port
from rich import print
from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text
from tqdm import tqdm

from testbed.swarmit.adapter import (
    GatewayAdapterBase,
    MarilibCloudAdapter,
    MarilibEdgeAdapter,
)
from testbed.swarmit.protocol import (
    DeviceType,
    PayloadMessage,
    PayloadOTAChunkRequest,
    PayloadOTAStartRequest,
    PayloadResetRequest,
    PayloadStartRequest,
    PayloadStopRequest,
    StatusType,
    SwarmitPayloadType,
    register_parsers,
)

CHUNK_SIZE = 128
COMMAND_TIMEOUT = 6
COMMAND_MAX_ATTEMPTS = 5
COMMAND_ATTEMPT_DELAY = 0.7
STATUS_TIMEOUT = 5
OTA_MAX_RETRIES_DEFAULT = 10
OTA_ACK_TIMEOUT_DEFAULT = 0.7
SERIAL_PORT_DEFAULT = get_default_port()
BROADCAST_ADDRESS = 0xFFFFFFFFFFFFFFFF
VOLTAGE_MAX = 3000  # mV
VOLTAGE_WARNING = 2200  # mV
VOLTAGE_DANGER = 2000  # mV


@dataclass
class NodeStatus:
    """Class that holds node status."""

    device: DeviceType = DeviceType.Unknown
    status: StatusType = StatusType.Bootloader
    battery: int = 0
    pos_x: int = 0
    pos_y: int = 0


@dataclass
class DataChunk:
    """Class that holds data chunks."""

    index: int
    size: int
    sha: bytes
    data: bytes


@dataclass
class StartOtaData:
    """Class that holds start ota data."""

    chunks: int = 0
    fw_hash: bytes = b""
    addrs: list[str] = dataclasses.field(default_factory=lambda: [])
    retries: int = 0


@dataclass
class Chunk:
    """Class that holds chunk status."""

    index: str = "0"
    size: str = "0B"
    acked: int = 0
    retries: int = 0

    def __repr__(self):
        return f"{dataclasses.asdict(self)}"


@dataclass
class TransferDataStatus:
    """Class that holds transfer data status for a single device."""

    chunks: list[Chunk] = dataclasses.field(default_factory=lambda: [])
    success: bool = False


@dataclass
class ResetLocation:
    """Class that holds reset location."""

    pos_x: int = 0
    pos_y: int = 0

    def __repr__(self):
        return f"(x={self.pos_x}, y={self.pos_y})"


def addr_to_hex(addr: int) -> str:
    """Convert an address to its hexadecimal representation."""
    return hexlify(addr.to_bytes(8, "big")).decode().upper()


def battery_level_color(level: int):
    if level > VOLTAGE_WARNING:
        return "green"
    elif level > VOLTAGE_DANGER:
        return "dark_orange"
    else:
        return "red"


def generate_status(status_data, devices=[], status_message="found"):
    data = {
        addr: device_data
        for addr, device_data in status_data.items()
        if (devices and addr in devices) or (not devices)
    }
    if not data:
        return Group(Text(f"\nNo device {status_message}\n"))

    header = Text(
        f"\n{len(data)} device{'s' if len(data) > 1 else ''} {status_message}\n"
    )

    table = Table()
    table.add_column("Device Addr", style="magenta", no_wrap=True)
    table.add_column(
        "Type",
        style="cyan",
        justify="center",
    )
    table.add_column(
        "Battery",
        style="cyan",
        justify="center",
    )
    table.add_column(
        "Position",
        style="cyan",
        justify="center",
    )
    table.add_column(
        "Status",
        style="green",
        justify="center",
        width=max([len(m) for m in StatusType.__members__]),
    )
    for device_addr, device_data in sorted(data.items()):

        table.add_row(
            f"{device_addr}",
            f"{device_data.device.name}",
            f"[{battery_level_color(device_data.battery)}]{device_data.battery / 1000:.2f}V ({int(device_data.battery / 3000 * 100)}%)",
            f"({(device_data.pos_x / 1e6):.2f}, {(device_data.pos_y / 1e6):.2f})",
            f"{'[bold cyan]' if device_data.status == StatusType.Running else '[bold green]'}{device_data.status.name}",
        )
    return Group(header, table)


def print_transfer_status(
    status: dict[str, TransferDataStatus], start_data: int
) -> None:
    """Print the transfer status."""
    print()
    print("[bold]Transfer status:[/]")
    transfer_status_table = Table()
    transfer_status_table.add_column(
        "Device Addr", style="magenta", no_wrap=True
    )
    transfer_status_table.add_column(
        "Chunks acked", style="green", justify="center"
    )

    with Live(transfer_status_table, refresh_per_second=4) as live:
        live.update(transfer_status_table)
        for device_addr, status in sorted(status.items()):
            chunks_col_color = "[green]" if status.success else "[bold red]"
            transfer_status_table.add_row(
                f"{device_addr}",
                f"{chunks_col_color}{len([chunk for chunk in status.chunks if bool(chunk.acked)])}/{start_data.chunks}",
            )


def wait_for_done(timeout, condition_func):
    """Wait for the condition to be met."""
    while timeout > 0:
        if condition_func():
            return True
        timeout -= 0.01
        time.sleep(0.01)
    return False


@dataclass
class ControllerSettings:
    """Class that holds controller settings."""

    serial_port: str = SERIAL_PORT_DEFAULT
    serial_baudrate: int = 1000000
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_use_tls: bool = False
    network_id: int = 1
    adapter: str = "serial"  # or "mqtt", "marilib-edge", "marilib-cloud"
    devices: list[str] = dataclasses.field(default_factory=lambda: [])
    ota_max_retries: int = OTA_MAX_RETRIES_DEFAULT
    ota_timeout: float = OTA_ACK_TIMEOUT_DEFAULT
    verbose: bool = False


class Controller:
    """Class used to control a swarm testbed."""

    def __init__(self, settings: ControllerSettings):
        self.logger = LOGGER.bind(context=__name__)
        self.settings = settings
        self._interface: GatewayAdapterBase = None
        self.status_data: dict[str, NodeStatus] = {}
        self.started_data: list[str] = []
        self.stopped_data: list[str] = []
        self.chunks: list[DataChunk] = []
        self.start_ota_data: StartOtaData = StartOtaData()
        self.transfer_data: dict[str, TransferDataStatus] = {}
        self._known_devices: dict[str, StatusType] = {}
        register_parsers()
        if self.settings.adapter == "cloud":
            self._interface = MarilibCloudAdapter(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                self.settings.mqtt_use_tls,
                self.settings.network_id,
                verbose=self.settings.verbose,
            )
        else:
            self._interface = MarilibEdgeAdapter(
                self.settings.serial_port,
                self.settings.serial_baudrate,
                verbose=self.settings.verbose,
            )
        self._interface.init(self.on_frame_received)

    @property
    def known_devices(self) -> dict[str, StatusType]:
        """Return the known devices."""
        if not self._known_devices:
            wait_for_done(COMMAND_TIMEOUT, lambda: False)
            self._known_devices = self.status_data
        return self._known_devices

    @property
    def running_devices(self) -> list[str]:
        """Return the running devices."""
        return [
            addr
            for addr, node in self.known_devices.items()
            if (
                (
                    node.status == StatusType.Running
                    or node.status == StatusType.Programming
                )
                and (
                    not self.settings.devices or addr in self.settings.devices
                )
            )
        ]

    @property
    def resetting_devices(self) -> list[str]:
        """Return the resetting devices."""
        return [
            device_addr
            for device_addr, node in self.known_devices.items()
            if (
                node.status == StatusType.Resetting
                and (
                    not self.settings.devices
                    or device_addr in self.settings.devices
                )
            )
        ]

    @property
    def ready_devices(self) -> list[str]:
        """Return the ready devices."""
        return [
            device_addr
            for device_addr, node in self.known_devices.items()
            if (
                node.status == StatusType.Bootloader
                and (
                    not self.settings.devices
                    or device_addr in self.settings.devices
                )
            )
        ]

    @property
    def interface(self) -> GatewayAdapterBase:
        """Return the interface."""
        return self._interface

    def terminate(self):
        """Terminate the controller."""
        self.interface.close()

    def send_payload(self, destination: int, payload: Payload):
        """Send a frame to the devices."""
        self.interface.send_payload(destination, payload)

    def on_frame_received(self, header, packet: Packet):
        """Handle the received frame."""
        # if self.settings.verbose:
        #     print()
        #     print(Frame(header, packet))
        if packet.payload_type < SwarmitPayloadType.SWARMIT_REQUEST_STATUS:
            return
        device_addr = f"{header.source:08X}"
        if (
            packet.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_STATUS
        ):
            status = NodeStatus(
                device=DeviceType(packet.payload.device),
                status=StatusType(packet.payload.status),
                battery=packet.payload.battery,
                pos_x=packet.payload.pos_x,
                pos_y=packet.payload.pos_y,
            )
            self.status_data.update({device_addr: status})
        elif (
            packet.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_START_ACK
        ):
            if device_addr in self.start_ota_data.addrs:
                return
            self.start_ota_data.addrs.append(device_addr)
        elif (
            packet.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_CHUNK_ACK
        ):
            try:
                acked = bool(
                    self.transfer_data[device_addr]
                    .chunks[packet.payload.index]
                    .acked
                )
            except (IndexError, KeyError):
                self.logger.warning(
                    "Chunk index out of range",
                    device_addr=device_addr,
                    chunk_index=packet.payload.index,
                )
                return
            if acked is False:
                self.transfer_data[device_addr].chunks[
                    packet.payload.index
                ].acked = 1
        elif packet.payload_type in [
            SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_GPIO,
            SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_LOG,
        ]:
            if (
                self.settings.devices
                and device_addr not in self.settings.devices
            ):
                return
            logger = self.logger.bind(
                device_addr=device_addr,
                notification=SwarmitPayloadType(packet.payload_type).name,
                timestamp=packet.payload.timestamp,
                data_size=packet.payload.count,
                data=packet.payload.data,
            )
            if (
                packet.payload_type
                == SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_GPIO
            ):
                logger.info("GPIO event")
            elif (
                packet.payload_type
                == SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_LOG
            ):
                logger.info("LOG event")
        elif packet.payload_type == SwarmitPayloadType.METRICS_PROBE:
            pass
        else:
            self.logger.error(
                "Unknown payload type", payload_type=packet.payload_type
            )

    def _live_status(
        self, devices=[], timeout=STATUS_TIMEOUT, message="found"
    ):
        """Request the live status of the testbed."""
        with Live(
            generate_status(self.status_data, devices, status_message=message),
            refresh_per_second=4,
        ) as live:
            while timeout > 0:
                live.update(
                    generate_status(
                        self.status_data, devices, status_message=message
                    )
                )
                timeout -= 0.01
                time.sleep(0.01)

    def status(self):
        """Request the status of the testbed."""
        self._live_status(self.settings.devices)

    def _send_start(self, device_addr: str):
        payload = PayloadStartRequest()
        self.send_payload(int(device_addr, 16), payload)

    def start(self):
        """Start the application."""
        ready_devices = self.ready_devices
        attempts = 0
        while attempts < COMMAND_MAX_ATTEMPTS and not all(
            self.status_data[addr].status == StatusType.Running
            for addr in ready_devices
        ):
            if not self.settings.devices:
                self._send_start(addr_to_hex(BROADCAST_ADDRESS))
            else:
                for device_addr in self.settings.devices:
                    if device_addr not in ready_devices:
                        continue
                    self._send_start(device_addr)
            attempts += 1
            time.sleep(COMMAND_ATTEMPT_DELAY)
        self._live_status(
            ready_devices, timeout=COMMAND_TIMEOUT, message="to start"
        )

    def stop(self):
        """Stop the application."""
        stoppable_devices = self.running_devices + self.resetting_devices

        attempts = 0
        while attempts < COMMAND_MAX_ATTEMPTS and not all(
            self.status_data[addr].status
            in [StatusType.Stopping, StatusType.Bootloader]
            for addr in stoppable_devices
        ):
            if not self.settings.devices:
                self.send_payload(BROADCAST_ADDRESS, PayloadStopRequest())
            else:
                for device_addr in self.settings.devices:
                    if (
                        device_addr not in stoppable_devices
                        or self.status_data[device_addr].status
                        in [StatusType.Stopping, StatusType.Bootloader]
                    ):
                        continue
                    self.send_payload(
                        int(device_addr, 16), PayloadStopRequest()
                    )
            attempts += 1
            time.sleep(COMMAND_ATTEMPT_DELAY)
        self._live_status(
            stoppable_devices, timeout=COMMAND_TIMEOUT, message="to stop"
        )

    def _send_reset(self, device_addr: int, location: ResetLocation):
        payload = PayloadResetRequest(
            pos_x=location.pos_x,
            pos_y=location.pos_y,
        )
        self.send_payload(device_addr, payload)

    def reset(self, locations: dict[str, ResetLocation]):
        """Reset the application."""
        ready_devices = self.ready_devices
        for device_addr in self.settings.devices:
            if device_addr not in ready_devices:
                continue
            print(
                f"Resetting device {device_addr} with location {locations[device_addr]}"
            )
            self._send_reset(int(device_addr, 16), locations[device_addr])

    def monitor(self):
        """Monitor the testbed."""
        self.logger.info("Monitoring testbed")
        while True:
            time.sleep(0.01)

    def _send_message(self, device_addr: int, message: str):
        payload = PayloadMessage(
            count=len(message),
            message=message.encode(),
        )
        self.send_payload(device_addr, payload)

    def send_message(self, message):
        """Send a message to the devices."""
        running_devices = self.running_devices
        if not self.settings.devices:
            self._send_message(BROADCAST_ADDRESS, message)
        else:
            for addr in self.settings.devices:
                if addr not in running_devices:
                    continue
                self._send_message(int(addr, 16), message)

    def _send_start_ota(
        self, device_addr: str, devices_to_flash: set[str], firmware: bytes
    ):
        def is_start_ota_acknowledged():
            if int(device_addr, 16) == BROADCAST_ADDRESS:
                return sorted(self.start_ota_data.addrs) == sorted(
                    devices_to_flash
                )
            else:
                return device_addr in self.start_ota_data.addrs

        payload = PayloadOTAStartRequest(
            fw_length=len(firmware),
            fw_chunk_count=len(self.chunks),
        )
        send_time = time.time()
        send = True
        while (
            not is_start_ota_acknowledged()
            and self.start_ota_data.retries <= self.settings.ota_max_retries
        ):
            if send is True:
                self.send_payload(int(device_addr, 16), payload)
                send_time = time.time()
                self.start_ota_data.retries += 1
            time.sleep(0.001)
            send = time.time() - send_time > self.settings.ota_timeout

    def start_ota(self, firmware) -> StartOtaData:
        """Start the OTA process."""
        self.start_ota_data = StartOtaData()
        self.chunks = []
        digest = hashes.Hash(hashes.SHA256())
        chunks_count = int(len(firmware) / CHUNK_SIZE) + int(
            len(firmware) % CHUNK_SIZE != 0
        )
        for chunk_idx in range(chunks_count):
            if chunk_idx == chunks_count - 1:
                chunk_size = len(firmware) % CHUNK_SIZE
            else:
                chunk_size = CHUNK_SIZE
            data = firmware[
                chunk_idx * CHUNK_SIZE : chunk_idx * CHUNK_SIZE + chunk_size
            ]
            digest.update(data)
            chunk_sha = hashes.Hash(hashes.SHA256())
            chunk_sha.update(data)
            self.chunks.append(
                DataChunk(
                    index=chunk_idx,
                    size=chunk_size,
                    sha=chunk_sha.finalize()[
                        :8
                    ],  # the first 8 bytes should be enough
                    data=data,
                )
            )
        self.start_ota_data.fw_hash = digest.finalize()
        self.start_ota_data.chunks = len(self.chunks)
        devices_to_flash = self.ready_devices
        if not self.settings.devices:
            print("Broadcast start ota notification...")
            self._send_start_ota(
                addr_to_hex(BROADCAST_ADDRESS), devices_to_flash, firmware
            )
        else:
            for addr in devices_to_flash:
                print(f"Sending start ota notification to {addr}...")
                self._send_start_ota(addr, devices_to_flash, firmware)
                time.sleep(0.2)
        return {
            "ota": self.start_ota_data,
            "acked": sorted(self.start_ota_data.addrs),
            "missed": sorted(
                set(devices_to_flash).difference(
                    set(self.start_ota_data.addrs)
                )
            ),
        }

    def send_chunk(
        self,
        chunk: DataChunk,
        device_addr: str,
        devices_to_flash: set[str],
    ):
        def is_chunk_acknowledged():
            if int(device_addr, 16) == BROADCAST_ADDRESS:
                return sorted(self.transfer_data.keys()) == sorted(
                    devices_to_flash
                ) and all(
                    [
                        status.chunks[chunk.index].acked
                        for status in self.transfer_data.values()
                    ]
                )
            else:
                return (
                    device_addr in self.transfer_data.keys()
                    and self.transfer_data[device_addr]
                    .chunks[chunk.index]
                    .acked
                )

        payload = PayloadOTAChunkRequest(
            index=chunk.index,
            count=chunk.size,
            sha=chunk.sha,
            chunk=chunk.data,
        )
        send_time = time.time()
        send = True
        retries_count = 0
        while (
            not is_chunk_acknowledged()
            and retries_count <= self.settings.ota_max_retries
        ):
            if send is True:
                if self.settings.verbose:
                    missing_acks = [
                        addr
                        for addr in devices_to_flash
                        if addr not in self.transfer_data
                        or not self.transfer_data[addr]
                        .chunks[chunk.index]
                        .acked
                    ]
                    print(
                        f"Transferring chunk {chunk.index}/{len(self.start_ota_data.chunks)} to {device_addr} "
                        f"- {retries_count} retries "
                        f"- {len(missing_acks)} missing acks: {', '.join(missing_acks) if missing_acks else 'none'}"
                    )
                self.send_payload(int(device_addr, 16), payload)
                if int(device_addr, 16) == BROADCAST_ADDRESS:
                    for addr in devices_to_flash:
                        self.transfer_data[addr].chunks[
                            chunk.index
                        ].retries = retries_count
                else:
                    self.transfer_data[device_addr].chunks[
                        chunk.index
                    ].retries = retries_count
                send_time = time.time()
                retries_count += 1
            time.sleep(0.001)
            send = time.time() - send_time > self.settings.ota_timeout

    def transfer(self, firmware, devices) -> dict[str, TransferDataStatus]:
        """Transfer the firmware to the devices."""
        data_size = len(firmware)
        use_progress_bar = not self.settings.verbose
        if use_progress_bar:
            progress = tqdm(
                range(0, data_size),
                unit="B",
                unit_scale=False,
                colour="green",
                ncols=100,
            )
            progress.set_description(
                f"Loading firmware ({int(data_size / 1024)}kB)"
            )
        self.transfer_data = {}
        for device_addr in devices:
            self.transfer_data[device_addr] = TransferDataStatus()
            self.transfer_data[device_addr].chunks = [
                Chunk(index=f"{i:03d}", size=f"{self.chunks[i].size:03d}B")
                for i in range(len(self.chunks))
            ]
        for chunk in self.chunks:
            if not self.settings.devices:
                self.send_chunk(
                    chunk,
                    addr_to_hex(BROADCAST_ADDRESS),
                    devices,
                )
            else:
                for addr in devices:
                    self.send_chunk(chunk, addr, devices)
            if use_progress_bar:
                progress.update(chunk.size)
        if use_progress_bar:
            progress.close()
        for device in devices:
            device_data = self.transfer_data.get(device)
            if device_data:
                device_data.success = all(
                    chunk.acked for chunk in device_data.chunks
                )
                self.transfer_data[device] = device_data
        return self.transfer_data
