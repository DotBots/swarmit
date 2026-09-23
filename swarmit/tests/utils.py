from __future__ import annotations

import dataclasses
import threading
import time

from dotbot_utils.protocol import Packet
from marilib.mari_protocol import (
    MARI_BROADCAST_ADDRESS,
    Frame,
    Header,
    NextProto,
)
from marilib.model import EdgeEvent, NodeInfoCloud
from marilib.protocol import PacketType

from swarmit.testbed.ota import BLOCK_SIZE_DEFAULT
from swarmit.testbed.protocol import (
    IMAGE_DIGEST_LEN,
    OTA_PROTOCOL_VERSION_BLOCK,
    DeviceType,
    PayloadDeviceInfo,
    PayloadEvent,
    PayloadOTABlockReportResp,
    PayloadOTAFinalizeResp,
    PayloadOTAStartAck,
    PayloadStatus,
    PayloadType,
    StatusType,
    encode_string_field,
)


def _decode_label(raw) -> str:
    """NUL-padded wire field -> str, the way the firmware reads it."""
    return bytes(raw).split(b"\x00", 1)[0].decode("utf-8", errors="replace")


@dataclasses.dataclass
class ChunkLossStrategy:
    """Simulated downlink loss for a node during a block OTA transfer."""

    # Chunk index the node pretends never to receive...
    drop_index: int | None = None
    # ...for this many transmissions, after which it accepts the chunk. A
    # count larger than the transfer's repair budget makes the loss permanent.
    drop_count: int = 0


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
        loss_strategy: ChunkLossStrategy = ChunkLossStrategy(),
        ota_should_fail: bool = False,
        ota_protocol_version: int = OTA_PROTOCOL_VERSION_BLOCK,
        info_gen: int = 1,
        image_name: str = "",
        image_version: str = "",
        answers_device_info: bool = True,
        lh2_homography_count: int = 0,
        lh2_flags: int = 0,
        pos_x: int = 0,
        pos_y: int = 0,
    ):
        self.adapter = adapter
        self.address = address
        self.device_type = device_type
        self.status = status
        self.battery = battery
        self.update_interval = update_interval
        self.loss_strategy = loss_strategy
        # Makes the node answer FINALIZE with ok=0 even if it got every chunk,
        # standing in for an image that does not match the expected SHA256.
        self.ota_should_fail = ota_should_fail
        self.ota_protocol_version = ota_protocol_version
        # Device-info state. `info_gen` is what the real net core echoes from
        # shared memory; bumping it is the only thing that makes the
        # controller ask again. `answers_device_info=False` stands in for
        # firmware predating the message, which reports generation 0 and
        # never replies.
        self.info_gen = info_gen
        self.image_name = image_name
        self.image_version = image_version
        self.answers_device_info = answers_device_info
        # LH2 state, as the net core reports it: the count doubles as the
        # basestation count, and the flags say the calibration is usable and
        # where it came from. Defaults are the uncalibrated bot, which is also
        # a bot that can never produce a fix - hence the (0, 0) position.
        self.lh2_homography_count = lh2_homography_count
        self.lh2_flags = lh2_flags
        self.pos_x = pos_x
        self.pos_y = pos_y
        # Staged by OTA_START, promoted to the reported image only once
        # FINALIZE verifies - so a failed transfer never renames the image.
        self._pending_name = ""
        self._pending_version = ""
        self.boot_count = info_gen
        # Requests answered, so a test can assert the fetch happened exactly
        # once per change rather than once per status frame.
        self.device_info_requests = 0
        self._stop_event = threading.Event()
        super().__init__(daemon=True)
        self.enabled = True
        self.total_chunks = 0
        self.ota_bytes_received = 0
        self.ota_expected_bytes_received = 0
        # Block-OTA device state, mirroring the bootloader: a set of chunk
        # indices written to "flash", plus the per-block bitmap it reports.
        self.received_chunks: set[int] = set()
        self.block_index = 0
        self.received_mask = 0
        self._drops_left = 0
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
                        pos_x=self.pos_x,
                        pos_y=self.pos_y,
                        info_gen=self.info_gen,
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
            self.received_chunks = set()
            self.block_index = 0
            self.received_mask = 0
            self._drops_left = self.loss_strategy.drop_count
            self._pending_name = _decode_label(packet.payload.image_name)
            self._pending_version = _decode_label(packet.payload.image_version)
            # A pre-block bootloader sends the ack with no version byte, which
            # the controller reads as version 1 and refuses to flash.
            ack = (
                PayloadOTAStartAck(version=self.ota_protocol_version)
                if self.ota_protocol_version >= OTA_PROTOCOL_VERSION_BLOCK
                else PayloadOTAStartAck()
            )
            self.send_packet(Packet().from_payload(ack))
        elif payload_type == PayloadType.SWARMIT_OTA_CHUNK:
            index = packet.payload.index
            # Simulated downlink loss: swallow the chunk without recording it.
            if self.loss_strategy.drop_index == index and self._drops_left > 0:
                self._drops_left -= 1
                return
            # No per-chunk ack: just write it and set the bitmap bit, resetting
            # the mask when the window moves on (as the bootloader does).
            if index not in self.received_chunks:
                self.received_chunks.add(index)
                self.ota_bytes_received += packet.payload.count
            block = index // BLOCK_SIZE_DEFAULT
            if block != self.block_index:
                self.block_index = block
                self.received_mask = 0
            self.received_mask |= 1 << (index % BLOCK_SIZE_DEFAULT)
            if len(self.received_chunks) == self.total_chunks:
                self.status = StatusType.Bootloader
        elif payload_type == PayloadType.SWARMIT_OTA_BLOCK_REPORT_REQ:
            self.send_packet(
                Packet().from_payload(
                    PayloadOTABlockReportResp(
                        block_index=self.block_index,
                        received_mask=self.received_mask,
                    )
                )
            )
        elif payload_type == PayloadType.SWARMIT_OTA_FINALIZE:
            complete = (
                len(self.received_chunks) == self.total_chunks
                and self.ota_bytes_received == self.ota_expected_bytes_received
            )
            ok = complete and not self.ota_should_fail
            self.send_packet(
                Packet().from_payload(PayloadOTAFinalizeResp(ok=int(ok)))
            )
            if ok:
                # The device record is only rewritten once the whole-image
                # SHA256 matches, and the generation counter moves with it.
                self.image_name = self._pending_name
                self.image_version = self._pending_version
                self.info_gen = (self.info_gen + 1) % 256
        elif payload_type == PayloadType.SWARMIT_REQUEST_MESSAGE:
            if not self.answers_device_info:
                return
            if packet.payload.msg_id != PayloadType.SWARMIT_DEVICE_INFO_RESP:
                return
            self.device_info_requests += 1
            self.send_packet(
                Packet().from_payload(
                    PayloadDeviceInfo(
                        info_version=2,
                        info_gen=self.info_gen,
                        boot_count=self.boot_count,
                        uptime_s=42,
                        bl_version=encode_string_field("0.9.0-test"),
                        net_version=encode_string_field("0.9.0-test"),
                        image_size=self.ota_expected_bytes_received,
                        image_digest=bytes(
                            [self.address & 0xFF] * IMAGE_DIGEST_LEN
                        ),
                        image_name=encode_string_field(self.image_name),
                        image_version=encode_string_field(self.image_version),
                        lh2_homography_count=self.lh2_homography_count,
                        lh2_flags=self.lh2_flags,
                    )
                )
            )

    def send_packet(self, packet: Packet):
        self.adapter.handle_data_received(
            EdgeEvent.to_bytes(EdgeEvent.NODE_DATA)
            + Frame(
                header=Header(
                    destination=0,
                    source=self.address,
                    type_=PacketType.DATA,
                    next_proto=NextProto.SWARMIT_TESTBED,
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
