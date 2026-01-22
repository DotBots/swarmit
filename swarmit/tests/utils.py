from __future__ import annotations

import dataclasses
import threading
import time

from dotbot_utils.protocol import Packet
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame, Header
from marilib.model import EdgeEvent, NodeInfoCloud
from marilib.protocol import PacketType

from swarmit.testbed.protocol import (
    DeviceType,
    PayloadEvent,
    PayloadOTAChunkAck,
    PayloadOTAStartAck,
    PayloadStatus,
    PayloadType,
    StatusType,
)


@dataclasses.dataclass
class ChunkAckStrategy:
    """Strategy for acknowledging OTA chunks."""

    ack_miss_index: int | None = None  # Index of chunk to skip acknowledgment
    ack_miss_retries: int = (
        0  # Number of retries before acknowledging the missed chunk
    )
    ack_out_of_range_index: int | None = (
        None  # Index of chunk to send invalid acknowledgment
    )


class LogEventTask(threading.Thread):

    def __init__(
        self, node: SwarmitNode, message, event_interval: float = 0.5
    ):
        self.node = node
        self.message = message
        self.event_interval = event_interval
        self._stop_event = threading.Event()
        super().__init__(daemon=True)

    def run(self):
        time.sleep(0.05)  # allow some time for initialization
        while not self._stop_event.is_set():
            self.node.send_packet(
                Packet().from_payload(
                    PayloadEvent(
                        timestamp=int(time.time()),
                        count=len(self.message),
                        data=self.message.encode(),
                    ),
                )
            )
            time.sleep(self.event_interval)

    def stop(self):
        self._stop_event.set()
        self.join()


class SwarmitNode(threading.Thread):

    def __init__(
        self,
        adapter: MarilibSerialAdapterMock,
        address: int,
        status: StatusType = StatusType.Bootloader,
        device_type: DeviceType = DeviceType.Unknown,
        battery: int = 2500,
        update_interval: float = 0.1,
        ack_strategy: ChunkAckStrategy = ChunkAckStrategy(),
        ota_should_fail: bool = False,
    ):
        self.adapter = adapter
        self.address = address
        self.device_type = device_type
        self.status = status
        self.battery = battery
        self.update_interval = update_interval
        self.ack_strategy = ack_strategy
        self.ota_should_fail = ota_should_fail
        self._stop_event = threading.Event()
        super().__init__(daemon=True)
        self.enabled = True
        self.total_chunks = 0
        self.last_chunk_acked = -1
        self.ota_bytes_received = 0
        self.ota_expected_bytes_received = 0
        self.start()
        self.log_event_task = LogEventTask(
            self,
            message=f"Node {self.address:08X} log event",
        )

    def run(self):
        while not self._stop_event.is_set():
            if self.enabled:
                packet = Packet().from_payload(
                    PayloadStatus(
                        device=self.device_type.value,
                        status=self.status.value,
                        battery=self.battery,
                        pos_x=2500,
                        pos_y=2500,
                    ),
                )
                self.send_packet(packet)
            time.sleep(self.update_interval)

    def stop(self):
        if self.log_event_task.is_alive():
            self.log_event_task.stop()
        self._stop_event.set()
        self.join()

    def start_log_event_task(self):
        self.log_event_task.start()

    def handle_frame(self, frame: Frame):
        if (
            frame.header.destination != self.address
            and frame.header.destination != MARI_BROADCAST_ADDRESS
        ):
            return
        packet = Packet.from_bytes(frame.payload)
        payload_type = PayloadType(packet.payload_type)
        if payload_type == PayloadType.SWARMIT_START:
            self.status = StatusType.Running
        elif payload_type == PayloadType.SWARMIT_STOP:
            self.status = StatusType.Bootloader
        elif payload_type == PayloadType.SWARMIT_RESET:
            self.status = StatusType.Resetting
        elif payload_type == PayloadType.SWARMIT_MESSAGE:
            print(
                f"Node {self.address:08X} received message: {packet.payload.message.decode()}"
            )
        elif payload_type == PayloadType.SWARMIT_OTA_START:
            self.status = StatusType.Programming
            self.total_chunks = packet.payload.fw_chunk_count
            self.ota_expected_bytes_received = packet.payload.fw_length
            self.send_packet(Packet().from_payload(PayloadOTAStartAck()))
        elif payload_type == PayloadType.SWARMIT_OTA_CHUNK:
            # ack miss simulation
            if self.ack_strategy.ack_miss_index == packet.payload.index:
                if self.ack_strategy.ack_miss_retries > 0:
                    self.ack_strategy.ack_miss_retries -= 1
                    return

            # only log index if not already acknowledged
            if self.last_chunk_acked != packet.payload.index:
                self.last_chunk_acked = packet.payload.index
                self.ota_bytes_received += packet.payload.count

            index_to_ack = packet.payload.index
            if (
                self.ack_strategy.ack_out_of_range_index
                == packet.payload.index
            ):
                index_to_ack = self.total_chunks + 1
            self.send_packet(
                Packet().from_payload(PayloadOTAChunkAck(index=index_to_ack))
            )
            if (
                index_to_ack == self.total_chunks - 1
                and not self.ota_should_fail
            ):
                assert (
                    self.ota_bytes_received == self.ota_expected_bytes_received
                )
                self.status = StatusType.Bootloader

    def send_packet(self, packet: Packet):
        self.adapter.handle_data_received(
            EdgeEvent.to_bytes(EdgeEvent.NODE_DATA)
            + Frame(
                header=Header(
                    destination=0, source=self.address, type_=PacketType.DATA
                ),
                payload=packet.to_bytes(),
            ).to_bytes()
        )


class MarilibAdapterMockBase:

    nodes: dict[int, SwarmitNode]

    def send_data(self, data: bytes):
        """Send data to the interface."""
        for node in self.nodes.values():
            node.handle_frame(Frame().from_bytes(data[1:]))


class MarilibSerialAdapterMock(MarilibAdapterMockBase):

    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.nodes = {}

    def init(self, on_data_received: callable):
        """Initialize the interface."""
        self.handle_data_received = on_data_received

    def add_node(self, node: SwarmitNode):
        self.nodes[node.address] = node
        frame = Frame(
            header=Header(
                destination=0, source=node.address, type_=PacketType.DATA
            ),
            payload=b"",
        )
        self.handle_data_received(
            EdgeEvent.to_bytes(EdgeEvent.NODE_JOINED) + frame.to_bytes()
        )

    def close(self):
        """Close the interface."""
        for node in self.nodes.values():
            frame = Frame(
                header=Header(
                    destination=0, source=node.address, type_=PacketType.DATA
                ),
                payload=b"",
            )
            self.handle_data_received(
                EdgeEvent.to_bytes(EdgeEvent.NODE_LEFT) + frame.to_bytes()
            )
            node.stop()
        self.nodes = {}


class MarilibMQTTAdapterMock(MarilibAdapterMockBase):

    def __init__(self, host, port, is_edge: bool, use_tls: bool = False):
        self.host = host
        self.port = port
        self.is_edge = is_edge
        self.network_id = None
        self.client = None
        self.on_data_received = None
        self.use_tls = use_tls
        self.nodes = {}

    def set_network_id(self, network_id: str):
        self.network_id = network_id

    def set_on_data_received(self, on_data_received: callable):
        self.handle_data_received = on_data_received

    def init(self):
        """Initialize the interface."""
        pass

    def add_node(self, node: SwarmitNode):
        self.nodes[node.address] = node
        frame = NodeInfoCloud(address=node.address, gateway_address=0)
        self.handle_data_received(
            EdgeEvent.to_bytes(EdgeEvent.NODE_JOINED) + frame.to_bytes()
        )

    def send_data_to_edge(self, data):
        self.send_data(data)
