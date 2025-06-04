"""Module containing classes for interfacing with the DotBot gateway."""

import base64
from abc import ABC, abstractmethod

import paho.mqtt.client as mqtt
from dotbot.serial_interface import SerialInterface
from rich import print


class GatewayAdapterBase(ABC):
    """Base class for interface adapters."""

    @abstractmethod
    def init(self, on_data_received: callable):
        """Initialize the interface."""

    @abstractmethod
    def close(self):
        """Close the interface."""

    @abstractmethod
    def send_data(self, data):
        """Send data to the interface."""


class SerialAdapter(GatewayAdapterBase):
    """Class used to interface with the serial port."""

    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.expected_length = -1
        self.bytes = bytearray()

    def on_byte_received(self, byte):
        if self.expected_length == -1:
            self.expected_length = int.from_bytes(byte, byteorder="little")
        else:
            self.bytes += byte
        if len(self.bytes) == self.expected_length:
            print(self.bytes)
            self.on_data_received(self.bytes)
            self.expected_length = -1
            self.bytes = bytearray()

    def init(self, on_data_received: callable):
        self.serial = SerialInterface(
            self.port, self.baudrate, self.on_byte_received
        )
        self.on_data_received = on_data_received
        print("[yellow]Connecting to gateway...[/]")
        self.serial.serial.flush()
        self.serial.write(b"\x01\xff")

    def close(self):
        print("[yellow]Disconnect from gateway...[/]")
        self.serial.write(b"\x01\xfe")
        self.serial.stop()

    def send_data(self, data):
        self.serial.write(len(data).to_bytes(1, "big"))
        self.serial.write(data)


class MQTTAdapter(GatewayAdapterBase):
    """Class used to interface with MQTT."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.client = None

    def on_message(self, client, userdata, message):
        try:
            self.on_data_received(base64.b64decode(message.payload))
        except Exception as e:
            # print the error and a stacktrace
            print(f"[red]Error decoding MQTT message: {e}[/]")
            print(f"[red]Message: {message.payload}[/]")

    def on_log(self, client, userdata, paho_log_level, messages):
        print(messages)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.client.subscribe("/pydotbot/edge_to_controller")

    def init(self, on_data_received: callable):
        self.on_data_received = on_data_received
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTProtocolVersion.MQTTv5,
        )
        self.client.tls_set_context(context=None)
        # self.client.on_log = self.on_log
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()

    def send_data(self, data):
        self.client.publish(
            "/pydotbot/controller_to_edge",
            base64.b64encode(data).decode(),
        )
