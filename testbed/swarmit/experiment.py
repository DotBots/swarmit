"""Module containing the swarmit experiment class."""

import dataclasses
import time
from dataclasses import dataclass
from typing import Optional

import serial
from cryptography.hazmat.primitives import hashes
from dotbot.logger import LOGGER
from dotbot.protocol import Frame, Header
from dotbot.serial_interface import SerialInterfaceException, get_default_port
from rich.console import Console
from rich.live import Live
from rich.table import Table
from tqdm import tqdm

from testbed.swarmit.adapter import (
    GatewayAdapterBase,
    MQTTAdapter,
    SerialAdapter,
)
from testbed.swarmit.protocol import (
    PayloadExperimentMessage,
    PayloadExperimentStartRequest,
    PayloadExperimentStatusRequest,
    PayloadExperimentStopRequest,
    PayloadOTAChunkRequest,
    PayloadOTAStartRequest,
    StatusType,
    SwarmitPayloadType,
    register_parsers,
)

CHUNK_SIZE = 128
SERIAL_PORT_DEFAULT = get_default_port()


@dataclass
class DataChunk:
    """Class that holds data chunks."""

    index: int
    size: int
    data: bytes


@dataclass
class ExperimentSettings:
    """Class that holds experiment settings."""

    serial_port: str = SERIAL_PORT_DEFAULT
    serial_baudrate: int = 1000000
    mqtt_host: str = "argus.paris.inria.fr"
    mqtt_port: int = 8883
    edge: bool = False
    devices: list[str] = dataclasses.field(default_factory=lambda: [])


class Experiment:
    """Class used to control an experiment."""

    def __init__(self, settings: ExperimentSettings):
        self.logger = LOGGER.bind(context=__name__)
        self.settings = settings
        self._interface: GatewayAdapterBase = None
        self.resp_ids: list[str] = []
        self.acked_ids: list[str] = []
        self.last_acked_index = -1
        self.chunks: list[DataChunk] = []
        self.status_data: dict[str, StatusType] = {}
        self._known_devices: dict[str, StatusType] = {}
        self.table = Table()
        self.table.add_column("Device ID", style="magenta", no_wrap=True)
        self.table.add_column("Status", style="green")
        self.expected_reply: Optional[SwarmitPayloadType] = None
        register_parsers()
        if self.settings.edge is True:
            self._interface = MQTTAdapter(
                self.settings.mqtt_host, self.settings.mqtt_port
            )
        else:
            try:
                self._interface = SerialAdapter(
                    self.settings.serial_port, self.settings.serial_baudrate
                )
            except (
                SerialInterfaceException,
                serial.serialutil.SerialException,
            ) as exc:
                console = Console()
                console.print(f"[bold red]Error:[/] {exc}")
        self._interface.init(self.on_data_received)

    @property
    def known_devices(self) -> dict[str, StatusType]:
        """Return the known devices."""
        if not self._known_devices:
            self._known_devices = self.status(display=False)
        return self._known_devices

    @property
    def running_devices(self) -> list[str]:
        """Return the running devices."""
        return [
            device_id
            for device_id, status in self.known_devices.items()
            if (
                status == StatusType.Running
                and (
                    not self.settings.devices
                    or device_id in self.settings.devices
                )
            )
        ]

    @property
    def ready_devices(self) -> list[str]:
        """Return the ready devices."""
        return [
            device_id
            for device_id, status in self.known_devices.items()
            if (
                status == StatusType.Ready
                and (
                    not self.settings.devices
                    or device_id in self.settings.devices
                )
            )
        ]

    @property
    def interface(self) -> GatewayAdapterBase:
        """Return the interface."""
        return self._interface

    def terminate(self):
        """Terminate the experiment."""
        self.interface.close()

    def send_frame(self, frame: Frame):
        """Send a frame to the devices."""
        self.interface.send_data(frame.to_bytes())

    def on_data_received(self, data):
        frame = Frame().from_bytes(data)
        device_id = f"{frame.payload.device_id:08X}"
        if (
            frame.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_STATUS
            and self.expected_reply
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_STATUS
        ):
            if device_id not in self.resp_ids:
                self.resp_ids.append(device_id)
            status = StatusType(frame.payload.status)
            self.status_data[device_id] = status
            self.table.add_row(
                f"0x{device_id}",
                f'{"[bold cyan]" if status == StatusType.Running else "[bold green]"}{status.name}',
            )
        elif (
            frame.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_START_ACK
            and self.expected_reply
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_START_ACK
        ):
            if device_id not in self.acked_ids:
                self.acked_ids.append(device_id)
        elif (
            frame.payload_type
            == SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_CHUNK_ACK
        ):
            if device_id not in self.acked_ids:
                self.acked_ids.append(device_id)
            self.last_acked_index = frame.payload.index
        elif frame.payload_type in [
            SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_GPIO,
            SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_LOG,
        ]:
            if (
                self.settings.devices
                and device_id not in self.settings.devices
            ):
                return
            logger = self.logger.bind(
                deviceid=device_id,
                notification=frame.payload_type.name,
                timestamp=frame.payload.timestamp,
                data_size=frame.payload.count,
                data=frame.payload.data,
            )
            if (
                frame.payload_type
                == SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_GPIO
            ):
                logger.info("GPIO event")
            elif (
                frame.payload_type
                == SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_LOG
            ):
                logger.info("LOG event")
        elif frame.payload_type != self.expected_reply:
            self.logger.warning(
                "Unexpected payload",
                payload_type=hex(frame.payload_type),
                expected=hex(self.expected_reply),
            )
        else:
            self.logger.error(
                "Unknown payload type", payload_type=frame.payload_type
            )

    def status(self, display=True):
        """Request the status of the experiment."""
        payload = PayloadExperimentStatusRequest(device_id=0)
        frame = Frame(header=Header(), payload=payload)
        self.expected_reply = SwarmitPayloadType.SWARMIT_NOTIFICATION_STATUS
        self.send_frame(frame)
        timeout = 0  # ms
        while timeout < 2000:
            timeout += 1
            time.sleep(0.0001)
        if self.status_data and display is True:
            with Live(self.table, refresh_per_second=4) as live:
                live.update(self.table)
                for device_id, status in self.status_data.items():
                    if status != StatusType.Off:
                        continue
                    self.table.add_row(device_id, f"[bold red]{status.name}")
        self.expected_reply = None
        return self.status_data

    def _send_start(self, device_id: str):
        payload = PayloadExperimentStartRequest(
            device_id=int(device_id, base=16)
        )
        self.send_frame(Frame(header=Header(), payload=payload))
        time.sleep(0.01)

    def start(self):
        """Start the experiment."""
        ready_devices = self.ready_devices
        if not self.settings.devices:
            self._send_start("0")
        else:
            for device_id in self.settings.devices:
                if device_id not in ready_devices:
                    continue
                self._send_start(device_id)

    def _send_stop(self, device_id: str):
        payload = PayloadExperimentStopRequest(
            device_id=int(device_id, base=16)
        )
        self.send_frame(Frame(header=Header(), payload=payload))
        time.sleep(0.01)

    def stop(self):
        """Stop the experiment."""
        running_devices = self.running_devices
        if not self.settings.devices:
            self._send_stop("0")
        else:
            for device_id in self.settings.devices:
                if device_id not in running_devices:
                    continue
                self._send_stop(device_id)

    def monitor(self):
        """Monitor the experiment."""
        self.logger.info("Monitoring experiment")
        while True:
            time.sleep(0.01)

    def _send_message(self, device_id, message):
        payload = PayloadExperimentMessage(
            device_id=int(device_id, base=16),
            count=len(message),
            message=message.encode(),
        )
        frame = Frame(header=Header(), payload=payload)
        self.send_frame(frame)

    def send_message(self, message):
        """Send a message to the devices."""
        running_devices = self.running_devices
        if not self.settings.devices:
            self._send_message("0", message)
        else:
            for device_id in self.settings.devices:
                if device_id not in running_devices:
                    continue
                self._send_message(device_id, message)

    def _send_start_ota(self, device_id: str, firmware: bytes):
        payload = PayloadOTAStartRequest(
            device_id=int(device_id, base=16),
            fw_length=len(firmware),
            fw_hash=self.fw_hash,
        )
        self.send_frame(Frame(header=Header(), payload=payload))

    def start_ota(self, firmware):
        """Start the OTA process."""
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
            self.chunks.append(
                DataChunk(
                    index=chunk_idx,
                    size=chunk_size,
                    data=data,
                )
            )
        print(f"Radio chunks ({CHUNK_SIZE}B): {len(self.chunks)}")
        self.fw_hash = digest.finalize()
        self.expected_reply = (
            SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_START_ACK
        )
        if not self.settings.devices:
            print("Broadcast start ota notification...")
            self._send_start_ota("0", firmware)
            self.acked_ids = []
            timeout = 0  # ms
            while timeout < 10000 and sorted(self.acked_ids) != sorted(
                self.known_devices
            ):
                timeout += 1
                time.sleep(0.0001)
        else:
            self.acked_ids = []
            for device_id in self.settings.devices:
                print(f"Sending start ota notification to {device_id}...")
                self._send_start_ota(device_id, firmware)
                timeout = 0  # ms
                while timeout < 10000 and device_id not in self.acked_ids:
                    timeout += 1
                    time.sleep(0.0001)
        self.expected_reply = None
        return self.acked_ids

    def send_chunk(self, chunk, device_id: str):
        send_time = time.time()
        send = True
        tries = 0

        def is_chunk_acknowledged():
            if device_id == "0":
                return self.last_acked_index == chunk.index and sorted(
                    self.acked_ids
                ) == sorted(self.known_devices)
            else:
                return (
                    self.last_acked_index == chunk.index
                    and device_id in self.acked_ids
                )

        self.acked_ids = []
        while tries < 3:
            if is_chunk_acknowledged():
                break
            if send is True:
                payload = PayloadOTAChunkRequest(
                    device_id=int(device_id, base=16),
                    index=chunk.index,
                    count=chunk.size,
                    chunk=chunk.data,
                )
                self.send_frame(Frame(header=Header(), payload=payload))
                send_time = time.time()
                tries += 1
            time.sleep(0.001)
            send = time.time() - send_time > 0.1
        else:
            raise Exception(
                f"chunk #{chunk.index} not acknowledged. Aborting."
            )
        self.last_acked_index = -1
        self.last_deviceid_ack = None

    def transfer(self, firmware):
        """Transfer the firmware to the devices."""
        data_size = len(firmware)
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
        self.expected_reply = (
            SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_CHUNK_ACK
        )
        for chunk in self.chunks:
            if not self.settings.devices:
                self.send_chunk(chunk, "0")
            else:
                for device_id in self.settings.devices:
                    self.send_chunk(chunk, device_id)
            progress.update(chunk.size)
        progress.close()
        self.expected_reply = None
