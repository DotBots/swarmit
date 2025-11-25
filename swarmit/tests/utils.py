from __future__ import annotations

import threading
import time

from dotbot_utils.protocol import Packet
from marilib.mari_protocol import MARI_BROADCAST_ADDRESS, Frame, Header
from marilib.model import EdgeEvent
from marilib.protocol import PacketType

from swarmit.testbed.protocol import (
    DeviceType,
    PayloadStatus,
    PayloadType,
    StatusType,
)


class SwarmitNode(threading.Thread):

    def __init__(
        self,
        adapter: SwarmitTestAdapter,
        address: int,
        status: StatusType = StatusType.Bootloader,
        device_type: DeviceType = DeviceType.Unknown,
        battery: int = 2500,
        update_interval: float = 1.0,
    ):
        self.adapter = adapter
        self.address = address
        self.device_type = device_type
        self.status = status
        self.battery = battery
        self.update_interval = update_interval
        self._stop_event = threading.Event()
        super().__init__(daemon=True)
        self.enabled = True
        self.start()

    def run(self):
        while not self._stop_event.is_set():
            if not self.enabled:
                time.sleep(0.1)
                continue
            self.send_packet(
                Packet().from_payload(
                    PayloadStatus(
                        device=self.device_type.value,
                        status=self.status.value,
                        battery=self.battery,
                        pos_x=0.5 * 1e6,
                        pos_y=0.5 * 1e6,
                    ),
                )
            )
            time.sleep(self.update_interval)

    def stop(self):
        self._stop_event.set()
        self.join()

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


class SwarmitTestAdapter:

    def __init__(self, port, baudrate, verbose: bool = False):
        self.port = port
        self.baudrate = baudrate
        self.verbose = verbose
        self.nodes = {}

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
        time.sleep(0.1)

    def init(self, on_data_received: callable):
        """Initialize the interface."""
        self.handle_data_received = on_data_received

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

    def send_data(self, data: bytes):
        """Send data to the interface."""
        for node in self.nodes.values():
            node.handle_frame(Frame().from_bytes(data[1:]))
