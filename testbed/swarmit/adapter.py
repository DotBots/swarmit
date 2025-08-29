"""Module containing classes for interfacing with the DotBot gateway."""

import time
from abc import ABC, abstractmethod

from dotbot.protocol import (
    Packet,
    Payload,
    ProtocolPayloadParserException,
)
from marilib.communication_adapter import MQTTAdapter as MarilibMQTTAdapter
from marilib.communication_adapter import SerialAdapter as MarilibSerialAdapter
from marilib.mari_protocol import Frame as MariFrame
from marilib.marilib_cloud import MarilibCloud
from marilib.marilib_edge import MarilibEdge
from marilib.model import EdgeEvent, MariNode
from rich import print


class GatewayAdapterBase(ABC):
    """Base class for interface adapters."""

    @abstractmethod
    def init(self, on_frame_received: callable):
        """Initialize the interface."""

    @abstractmethod
    def close(self):
        """Close the interface."""

    @abstractmethod
    def send_payload(self, destination: int, payload: Payload):
        """Send payload to the interface."""


class MarilibEdgeAdapter(GatewayAdapterBase):
    """Class used to interface with Marilib."""

    def on_event(self, event: EdgeEvent, event_data: MariNode | MariFrame):
        if event == EdgeEvent.NODE_JOINED:
            if self.verbose:
                print("[green]Node joined:[/]", event_data)
        elif event == EdgeEvent.NODE_LEFT:
            if self.verbose:
                print("[orange]Node left:[/]", event_data)
        elif event == EdgeEvent.NODE_DATA:
            try:
                packet = Packet.from_bytes(event_data.payload)
            except (ValueError, ProtocolPayloadParserException) as exc:
                print(f"[red]Error parsing packet: {exc}[/]")
                return
            if not hasattr(self, "on_frame_received"):
                return
            self.on_frame_received(event_data.header, packet)

    def __init__(self, port: str, baudrate: int, verbose: bool = False):
        self.verbose = verbose
        self.mari = MarilibEdge(
            self.on_event, MarilibSerialAdapter(port, baudrate)
        )

    def _busy_wait(self, timeout: int):
        """Wait for the condition to be met."""
        while timeout > 0:
            self.mari.update()
            timeout -= 0.1
            time.sleep(0.1)

    def init(self, on_frame_received: callable):
        self.on_frame_received = on_frame_received
        self._busy_wait(3)
        if self.verbose:
            print("[yellow]Mari nodes available:[/]")
            print(self.mari.nodes)

    def close(self):
        pass

    def send_payload(self, destination: int, payload: Payload):
        self.mari.send_frame(
            dst=destination,
            payload=Packet.from_payload(payload).to_bytes(),
        )


class MarilibCloudAdapter(GatewayAdapterBase):
    """Class used to interface with Marilib."""

    def on_event(self, event: EdgeEvent, event_data: MariNode | MariFrame):
        if event == EdgeEvent.NODE_JOINED:
            if self.verbose:
                print("[green]Node joined:[/]", event_data)
        elif event == EdgeEvent.NODE_LEFT:
            if self.verbose:
                print("[orange]Node left:[/]", event_data)
        elif event == EdgeEvent.NODE_DATA:
            try:
                packet = Packet.from_bytes(event_data.payload)
            except (ValueError, ProtocolPayloadParserException) as exc:
                print(f"[red]Error parsing packet: {exc}[/]")
                return
            if not hasattr(self, "on_frame_received"):
                return
            self.on_frame_received(event_data.header, packet)

    def __init__(
        self,
        host: str,
        port: int,
        use_tls: bool,
        network_id: int,
        verbose: bool = False,
    ):
        self.verbose = verbose
        self.mari = MarilibCloud(
            self.on_event,
            MarilibMQTTAdapter(host, port, use_tls=use_tls, is_edge=False),
            network_id,
        )

    def _busy_wait(self, timeout):
        """Wait for the condition to be met."""
        while timeout > 0:
            self.mari.update()
            timeout -= 0.1
            time.sleep(0.1)

    def init(self, on_frame_received: callable):
        self.on_frame_received = on_frame_received
        self._busy_wait(3)
        if self.verbose:
            print("[yellow]Mari nodes available:[/]")
            print(self.mari.nodes)

    def close(self):
        pass

    def send_payload(self, destination: int, payload: Payload):
        self.mari.send_frame(
            dst=destination,
            payload=Packet.from_payload(payload).to_bytes(),
        )
