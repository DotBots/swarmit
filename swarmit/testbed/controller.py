"""Module containing the swarmit controller class."""

import asyncio
import dataclasses
import time
from binascii import hexlify
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from dotbot_utils.protocol import Payload
from dotbot_utils.serial_interface import get_default_port

from swarmit.testbed.adapter import (
    GatewayAdapterBase,
    MarilibCloudAdapter,
    MarilibEdgeAdapter,
)
from swarmit.testbed.logger import LOGGER
from swarmit.testbed.protocol import (
    DeviceType,
    PayloadMessage,
    PayloadOTAChunk,
    PayloadOTAStart,
    PayloadReset,
    PayloadStart,
    PayloadStop,
    PayloadType,
    StatusType,
)

CHUNK_SIZE = 128
COMMAND_MAX_ATTEMPTS = 5
COMMAND_ATTEMPT_DELAY = 0.7
INACTIVE_TIMEOUT = 3  # s
OTA_MAX_RETRIES_DEFAULT = 10
OTA_ACK_TIMEOUT_DEFAULT = 0.7
SERIAL_PORT_DEFAULT = get_default_port()
BROADCAST_ADDRESS = 0xFFFFFFFFFFFFFFFF
VOLTAGE_FULL = 2900  # mV
VOLTAGE_WARNING = 1500  # mV


@dataclass
class NodeStatus:
    """Class that holds node status."""

    device: DeviceType = DeviceType.Unknown
    status: StatusType = StatusType.Bootloader
    battery: int = 0
    pos_x: int = 0
    pos_y: int = 0
    last_updated_at: float = 0


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
    fw_length: int = 0
    fw_hash: bytes = b""
    addrs: list[str] = dataclasses.field(default_factory=lambda: [])
    retries: int = 0
    status: str = "idle"  # "idle" | "pending" | "done"
    acked: list[str] = dataclasses.field(default_factory=lambda: [])
    missed: list[str] = dataclasses.field(default_factory=lambda: [])


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
    map_size: str = "2500x2500"
    ota_max_retries: int = OTA_MAX_RETRIES_DEFAULT
    ota_timeout: float = OTA_ACK_TIMEOUT_DEFAULT
    adapter_wait_timeout: float = 3
    verbose: bool = False


class Controller:
    """Class used to control a swarm testbed."""

    def __init__(self, settings: ControllerSettings):
        self.logger = LOGGER.bind(__context=__name__)
        self.settings = settings
        self._interface: GatewayAdapterBase = None
        self.status_data: dict[str, NodeStatus] = {}
        self.chunks: list[DataChunk] = []
        self.start_ota_data: StartOtaData = StartOtaData()
        self.transfer_data: dict[str, TransferDataStatus] = {}
        # Initialised in setup():
        self._loop: asyncio.AbstractEventLoop = None
        self._frame_queue: asyncio.Queue = None
        self._stop_event: asyncio.Event = None
        self._frame_task: asyncio.Task = None
        self._cleanup_task: asyncio.Task = None

    async def setup(self):
        """Initialise async primitives, adapter and background tasks."""
        self._loop = asyncio.get_running_loop()
        self._frame_queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        if self.settings.adapter == "cloud":
            self._interface = MarilibCloudAdapter(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                self.settings.mqtt_use_tls,
                self.settings.network_id,
                verbose=self.settings.verbose,
                busy_wait_timeout=self.settings.adapter_wait_timeout,
            )
        else:
            self._interface = MarilibEdgeAdapter(
                self.settings.serial_port,
                self.settings.serial_baudrate,
                verbose=self.settings.verbose,
                busy_wait_timeout=self.settings.adapter_wait_timeout,
            )
        self._interface.init(self._on_frame_received)
        self._frame_task = asyncio.create_task(self._process_frames())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    @property
    def interface(self) -> GatewayAdapterBase:
        """Return the gateway adapter interface."""
        return self._interface

    @property
    def running_devices(self) -> list[str]:
        """Return the running devices."""
        return [
            addr
            for addr, node in self.status_data.items()
            if node.status in (StatusType.Running, StatusType.Programming)
            and (not self.settings.devices or addr in self.settings.devices)
        ]

    @property
    def resetting_devices(self) -> list[str]:
        """Return the resetting devices."""
        return [
            addr
            for addr, node in self.status_data.items()
            if node.status == StatusType.Resetting
            and (not self.settings.devices or addr in self.settings.devices)
        ]

    @property
    def ready_devices(self) -> list[str]:
        """Return the ready (bootloader) devices."""
        return [
            addr
            for addr, node in self.status_data.items()
            if node.status == StatusType.Bootloader
            and (not self.settings.devices or addr in self.settings.devices)
        ]

    # ------------------------------------------------------------------
    # Internal frame bridge (called from marilib's thread)
    # ------------------------------------------------------------------

    def _on_frame_received(self, header, packet):
        """Bridge marilib's thread callback into the asyncio queue."""
        try:
            self._loop.call_soon_threadsafe(
                self._frame_queue.put_nowait, (header, packet)
            )
        except RuntimeError:
            pass  # loop already closed

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _process_frames(self):
        while not self._stop_event.is_set():
            try:
                header, packet = await asyncio.wait_for(
                    self._frame_queue.get(), timeout=0.1
                )
                await self._handle_frame(header, packet)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _handle_frame(self, header, packet):
        """Process a single received frame."""
        device_addr = f"{header.source:08X}"
        if packet.payload_type == PayloadType.SWARMIT_STATUS:
            status = NodeStatus(
                device=DeviceType(packet.payload.device),
                status=StatusType(packet.payload.status),
                battery=packet.payload.battery,
                pos_x=packet.payload.pos_x,
                pos_y=packet.payload.pos_y,
                last_updated_at=time.time(),
            )
            print(device_addr, status)
            self.status_data[device_addr] = status
        elif (
            packet.payload_type == PayloadType.SWARMIT_OTA_START_ACK
            and device_addr not in self.start_ota_data.addrs
        ):
            self.start_ota_data.addrs.append(device_addr)
        elif packet.payload_type == PayloadType.SWARMIT_OTA_CHUNK_ACK:
            try:
                acked = bool(
                    self.transfer_data[device_addr]
                    .chunks[packet.payload.index]
                    .acked
                )
            except (IndexError, KeyError):
                self.logger.debug(
                    "Chunk index out of range",
                    device_addr=device_addr,
                    chunk_index=packet.payload.index,
                )
                return
            if not acked:
                self.transfer_data[device_addr].chunks[
                    packet.payload.index
                ].acked = 1
        elif packet.payload_type == PayloadType.SWARMIT_EVENT_LOG:
            if (
                self.settings.devices
                and device_addr not in self.settings.devices
            ):
                return
            self.logger.bind(
                device_addr=device_addr,
                notification=PayloadType(packet.payload_type).name,
                timestamp=packet.payload.timestamp,
                data_size=packet.payload.count,
                data=packet.payload.data,
            ).info("LOG event")

    async def _cleanup_loop(self):
        while not self._stop_event.is_set():
            self.cleanup_inactive(INACTIVE_TIMEOUT)
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break

    def cleanup_inactive(self, timeout):
        """Remove devices that haven't sent a status frame recently."""
        now = time.time()
        inactive = [
            addr
            for addr, status in self.status_data.items()
            if now - status.last_updated_at > timeout
        ]
        for addr in inactive:
            del self.status_data[addr]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def terminate(self):
        """Cancel background tasks and close the adapter."""
        self._stop_event.set()
        for task in (self._cleanup_task, self._frame_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._interface.close()

    # ------------------------------------------------------------------
    # Low-level send helpers (synchronous – marilib API is sync)
    # ------------------------------------------------------------------

    def send_payload(self, destination: int, payload: Payload):
        """Send a frame to the devices."""
        self._interface.send_payload(destination, payload)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def start(self, devices=None):
        """Send start commands and wait for acknowledgement."""
        if devices is None:
            devices = self.settings.devices or []
        ready_devices = self.ready_devices
        devices_to_start = (
            ready_devices
            if not devices
            else [d for d in devices if d in ready_devices]
        )
        attempts = 0
        while attempts < COMMAND_MAX_ATTEMPTS and not all(
            addr in self.status_data
            and self.status_data[addr].status == StatusType.Running
            for addr in devices_to_start
        ):
            if not devices:
                self.send_payload(BROADCAST_ADDRESS, PayloadStart())
            else:
                for addr in devices_to_start:
                    self.send_payload(int(addr, 16), PayloadStart())
            attempts += 1
            await asyncio.sleep(COMMAND_ATTEMPT_DELAY)

    async def stop(self, devices=None):
        """Send stop commands and wait for acknowledgement."""
        if devices is None:
            devices = self.settings.devices or []
        stoppable = self.running_devices + self.resetting_devices
        devices_to_stop = (
            stoppable
            if not devices
            else [d for d in devices if d in stoppable]
        )
        attempts = 0
        while attempts < COMMAND_MAX_ATTEMPTS and not all(
            self.status_data[addr].status
            in (StatusType.Stopping, StatusType.Bootloader)
            for addr in devices_to_stop
        ):
            if not devices:
                self.send_payload(BROADCAST_ADDRESS, PayloadStop())
            else:
                for addr in devices_to_stop:
                    self.send_payload(int(addr, 16), PayloadStop())
            attempts += 1
            await asyncio.sleep(COMMAND_ATTEMPT_DELAY)

    async def reset(self, locations: dict[str, ResetLocation]):
        """Send reset commands to ready devices in *locations*."""
        ready_devices = self.ready_devices
        for device_addr, location in locations.items():
            if device_addr not in ready_devices:
                continue
            print(f"Resetting device {device_addr} with location {location}")
            self.send_payload(
                int(device_addr, 16),
                PayloadReset(pos_x=location.pos_x, pos_y=location.pos_y),
            )
        await asyncio.sleep(0)

    async def send_message(self, message, devices=None):
        """Send a text message to devices."""
        if devices is None:
            devices = self.settings.devices or []
        running_devices = self.running_devices
        if not devices:
            self.send_payload(
                BROADCAST_ADDRESS,
                PayloadMessage(count=len(message), message=message.encode()),
            )
        else:
            for addr in devices:
                if addr not in running_devices:
                    continue
                self.send_payload(
                    int(addr, 16),
                    PayloadMessage(
                        count=len(message), message=message.encode()
                    ),
                )
        await asyncio.sleep(0)

    # ------------------------------------------------------------------
    # OTA
    # ------------------------------------------------------------------

    async def _send_start_ota(
        self,
        device_addr: str,
        devices_to_flash: list[str],
        ota_timeout: float,
        ota_max_retries: int,
    ):
        def is_acked():
            if int(device_addr, 16) == BROADCAST_ADDRESS:
                return sorted(self.start_ota_data.addrs) == sorted(
                    devices_to_flash
                )
            return device_addr in self.start_ota_data.addrs

        payload = PayloadOTAStart(
            fw_length=self.start_ota_data.fw_length,
            fw_chunk_count=len(self.chunks),
        )
        send_time = time.time()
        send = True
        while (
            not is_acked() and self.start_ota_data.retries <= ota_max_retries
        ):
            if send:
                self.send_payload(int(device_addr, 16), payload)
                send_time = time.time()
                self.start_ota_data.retries += 1
            await asyncio.sleep(0)  # yield so _process_frames can run
            send = time.time() - send_time > ota_timeout

    async def start_ota(self, firmware, devices=None) -> dict:
        """Prepare firmware chunks and negotiate OTA start with devices.

        Returns a dict with keys: ``ota``, ``acked``, ``missed``.
        """
        if devices is None:
            devices = self.settings.devices or []
        ota_timeout = self.settings.ota_timeout
        ota_max_retries = self.settings.ota_max_retries

        self.start_ota_data = StartOtaData(status="pending")
        self.chunks = []
        digest = hashes.Hash(hashes.SHA256())
        chunks_count = int(len(firmware) / CHUNK_SIZE) + int(
            len(firmware) % CHUNK_SIZE != 0
        )
        for chunk_idx in range(chunks_count):
            if chunk_idx == chunks_count - 1:
                chunk_size = (
                    len(firmware) % CHUNK_SIZE
                    if len(firmware) % CHUNK_SIZE
                    else CHUNK_SIZE
                )
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
                    sha=chunk_sha.finalize()[:8],
                    data=data,
                )
            )
        self.start_ota_data.fw_hash = digest.finalize()
        self.start_ota_data.fw_length = len(firmware)
        self.start_ota_data.chunks = len(self.chunks)
        devices_to_flash = self.ready_devices
        if not devices:
            print("Broadcast start ota notification...")
            await self._send_start_ota(
                addr_to_hex(BROADCAST_ADDRESS),
                devices_to_flash,
                ota_timeout,
                ota_max_retries,
            )
        else:
            for addr in devices:
                print(f"Sending start ota notification to {addr}...")
                await self._send_start_ota(
                    addr, devices, ota_timeout, ota_max_retries
                )
                await asyncio.sleep(0.2)
        self.start_ota_data.acked = sorted(self.start_ota_data.addrs)
        self.start_ota_data.missed = sorted(
            set(devices).difference(set(self.start_ota_data.addrs))
        )
        self.start_ota_data.status = "done"
        return {
            "ota": self.start_ota_data,
            "acked": self.start_ota_data.acked,
            "missed": self.start_ota_data.missed,
        }

    async def send_chunk(
        self,
        chunk: DataChunk,
        device_addr: str,
        devices_to_flash: list[str],
    ):
        """Send a single OTA chunk and wait for all ACKs."""
        ota_timeout = self.settings.ota_timeout
        ota_max_retries = self.settings.ota_max_retries

        def is_chunk_acknowledged():
            if int(device_addr, 16) == BROADCAST_ADDRESS:
                return sorted(self.transfer_data.keys()) == sorted(
                    devices_to_flash
                ) and all(
                    s.chunks[chunk.index].acked
                    for s in self.transfer_data.values()
                )
            return (
                device_addr in self.transfer_data
                and self.transfer_data[device_addr].chunks[chunk.index].acked
            )

        payload = PayloadOTAChunk(
            index=chunk.index,
            count=chunk.size,
            sha=chunk.sha,
            chunk=chunk.data,
        )
        send_time = time.time()
        send = True
        retries_count = 0
        while not is_chunk_acknowledged() and retries_count <= ota_max_retries:
            if send:
                self.send_payload(int(device_addr, 16), payload)
                if self.settings.verbose:
                    missing = [
                        a
                        for a in devices_to_flash
                        if a not in self.transfer_data
                        or not self.transfer_data[a].chunks[chunk.index].acked
                    ]
                    print(
                        f"Transferring chunk {chunk.index + 1}/"
                        f"{self.start_ota_data.chunks} to {device_addr} "
                        f"- {retries_count} retries "
                        f"- {len(missing)} missing acks: "
                        f"{', '.join(missing) if missing else 'none'}"
                    )
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
            await asyncio.sleep(0)  # yield so _process_frames can run
            send = time.time() - send_time > ota_timeout

    async def transfer(
        self, devices: list[str]
    ) -> dict[str, TransferDataStatus]:
        """Transfer all firmware chunks to *devices*.

        ``start_ota()`` must be called first to populate ``self.chunks``.
        """
        self.transfer_data = {}
        for addr in devices:
            self.transfer_data[addr] = TransferDataStatus(
                chunks=[
                    Chunk(
                        index=f"{i:03d}",
                        size=f"{self.chunks[i].size:03d}B",
                    )
                    for i in range(len(self.chunks))
                ]
            )
        for chunk in self.chunks:
            if not devices:
                await self.send_chunk(
                    chunk, addr_to_hex(BROADCAST_ADDRESS), devices
                )
            else:
                for addr in devices:
                    await self.send_chunk(chunk, addr, devices)
        if self.settings.verbose:
            retries_count = sum(
                self.transfer_data[addr].chunks[i].retries
                for i in range(len(self.chunks))
                for addr in devices
            )
            if not self.settings.devices:
                retries_count = (
                    int(retries_count / len(devices)) if devices else 0
                )
            print(f"Transfer completed with {retries_count} retries")
        for addr in devices:
            device_data = self.transfer_data.get(addr)
            if device_data:
                device_data.success = all(c.acked for c in device_data.chunks)
        return self.transfer_data
