"""Swarmit protocol definition."""

import dataclasses
from dataclasses import dataclass
from enum import Enum, IntEnum

from dotbot.protocol import Packet, PacketFieldMetadata, register_parser


class StatusType(Enum):
    """Types of device status."""

    Ready = 0
    Running = 1
    Off = 2


class SwarmitPayloadType(IntEnum):
    """Types of DotBot payload types."""

    SWARMIT_REQUEST_STATUS = 0x80
    SWARMIT_REQUEST_START = 0x81
    SWARMIT_REQUEST_STOP = 0x82
    SWARMIT_REQUEST_OTA_START = 0x83
    SWARMIT_REQUEST_OTA_CHUNK = 0x84
    SWARMIT_NOTIFICATION_STATUS = 0x85
    SWARMIT_NOTIFICATION_OTA_START_ACK = 0x86
    SWARMIT_NOTIFICATION_OTA_CHUNK_ACK = 0x87
    SWARMIT_NOTIFICATION_EVENT_GPIO = 0x88
    SWARMIT_NOTIFICATION_EVENT_LOG = 0x89
    SWARMIT_MESSAGE = 0x8A


@dataclass
class PayloadRequest(Packet):
    """Dataclass that holds an application request packet (start/stop/status)."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
        ]
    )

    device_id: int = 0x0000000000000000


@dataclass
class PayloadStatusRequest(PayloadRequest):
    """Dataclass that holds an application status request packet."""


@dataclass
class PayloadStartRequest(PayloadRequest):
    """Dataclass that holds an application start request packet."""


@dataclass
class PayloadStopRequest(PayloadRequest):
    """Dataclass that holds an application stop request packet."""


@dataclass
class PayloadOTAStartRequest(Packet):
    """Dataclass that holds an OTA start packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="fw_length", disp="len.", length=4),
            PacketFieldMetadata(
                name="fw_chunk_counts", disp="chunks", length=4
            ),
            PacketFieldMetadata(
                name="fw_hash", disp="hash.", type_=bytes, length=32
            ),
        ]
    )

    device_id: int = 0x0000000000000000
    fw_length: int = 0
    fw_chunk_count: int = 0
    fw_hash: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadOTAChunkRequest(Packet):
    """Dataclass that holds an OTA chunk packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="index", disp="idx", length=4),
            PacketFieldMetadata(name="count", disp="size"),
            PacketFieldMetadata(name="chunk", type_=bytes, length=0),
        ]
    )

    device_id: int = 0x0000000000000000
    index: int = 0
    count: int = 0
    chunk: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadStatusNotification(Packet):
    """Dataclass that holds an application status notification packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="status", disp="st."),
        ]
    )

    device_id: int = 0x0000000000000000
    status: StatusType = StatusType.Ready


@dataclass
class PayloadOTAStartAckNotification(Packet):
    """Dataclass that holds an application OTA start ACK notification packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
        ]
    )

    device_id: int = 0x0000000000000000


@dataclass
class PayloadOTAChunkAckNotification(Packet):
    """Dataclass that holds an application OTA chunk ACK notification packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="index", disp="idx", length=4),
            PacketFieldMetadata(name="hashes_match", disp="match"),
        ]
    )

    device_id: int = 0x0000000000000000
    index: int = 0
    hashes_match: int = 0


@dataclass
class PayloadEventNotification(Packet):
    """Dataclass that holds an event notification packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="timestamp", disp="ts", length=4),
            PacketFieldMetadata(name="count", disp="len."),
            PacketFieldMetadata(
                name="data", disp="data", type_=bytes, length=0
            ),
        ]
    )

    device_id: int = 0x0000000000000000
    timestamp: int = 0
    count: int = 0
    data: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadMessage(Packet):
    """Dataclass that holds a message packet."""

    metadata: list[PacketFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PacketFieldMetadata(name="device_id", disp="id", length=8),
            PacketFieldMetadata(name="count", disp="len."),
            PacketFieldMetadata(
                name="message", disp="msg", type_=bytes, length=0
            ),
        ]
    )

    device_id: int = 0x0000000000000000
    count: int = 0
    message: bytes = dataclasses.field(default_factory=lambda: bytearray)


def register_parsers():
    # Register all swarmit specific parsers at module level
    register_parser(
        SwarmitPayloadType.SWARMIT_REQUEST_STATUS,
        PayloadStatusRequest,
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_REQUEST_START, PayloadStartRequest
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_REQUEST_STOP, PayloadStopRequest
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_REQUEST_OTA_START, PayloadOTAStartRequest
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_REQUEST_OTA_CHUNK, PayloadOTAChunkRequest
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_NOTIFICATION_STATUS,
        PayloadStatusNotification,
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_START_ACK,
        PayloadOTAStartAckNotification,
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_NOTIFICATION_OTA_CHUNK_ACK,
        PayloadOTAChunkAckNotification,
    )
    register_parser(
        SwarmitPayloadType.SWARMIT_NOTIFICATION_EVENT_LOG,
        PayloadEventNotification,
    )
    register_parser(SwarmitPayloadType.SWARMIT_MESSAGE, PayloadMessage)
