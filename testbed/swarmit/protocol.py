"""Swarmit protocol definition."""

import dataclasses
from dataclasses import dataclass
from enum import Enum, IntEnum

from dotbot.protocol import Payload, PayloadFieldMetadata, register_parser


class StatusType(Enum):
    """Types of device status."""

    Bootloader = 0
    Running = 1
    Stopping = 2
    Resetting = 3
    Programming = 4


class SwarmitPayloadType(IntEnum):
    """Types of DotBot payload types."""

    # Requests
    SWARMIT_REQUEST_STATUS = 0x80
    SWARMIT_REQUEST_START = 0x81
    SWARMIT_REQUEST_STOP = 0x82
    SWARMIT_REQUEST_RESET = 0x83
    SWARMIT_REQUEST_OTA_START = 0x84
    SWARMIT_REQUEST_OTA_CHUNK = 0x85

    # Notifications
    SWARMIT_NOTIFICATION_STATUS = 0x90
    SWARMIT_NOTIFICATION_OTA_START_ACK = 0x93
    SWARMIT_NOTIFICATION_OTA_CHUNK_ACK = 0x94
    SWARMIT_NOTIFICATION_EVENT_GPIO = 0x95
    SWARMIT_NOTIFICATION_EVENT_LOG = 0x96

    # Custom messages
    SWARMIT_MESSAGE = 0xA0


# Requests


@dataclass
class PayloadRequest(Payload):
    """Dataclass that holds an application request packet (start/stop/status)."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: []
    )


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
class PayloadResetRequest(Payload):
    """Dataclass that holds an application reset request packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="pos_x", length=4),
            PayloadFieldMetadata(name="pos_y", length=4),
        ]
    )

    pos_x: int = 0
    pos_y: int = 0


@dataclass
class PayloadOTAStartRequest(Payload):
    """Dataclass that holds an OTA start packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="fw_length", disp="len.", length=4),
            PayloadFieldMetadata(
                name="fw_chunk_counts", disp="chunks", length=4
            ),
            PayloadFieldMetadata(
                name="fw_hash", disp="hash.", type_=bytes, length=32
            ),
        ]
    )

    fw_length: int = 0
    fw_chunk_count: int = 0
    fw_hash: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadOTAChunkRequest(Payload):
    """Dataclass that holds an OTA chunk packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="index", disp="idx", length=4),
            PayloadFieldMetadata(name="count", disp="size"),
            PayloadFieldMetadata(name="chunk", type_=bytes, length=0),
        ]
    )

    index: int = 0
    count: int = 0
    chunk: bytes = dataclasses.field(default_factory=lambda: bytearray)


# Notifications


@dataclass
class PayloadStatusNotification(Payload):
    """Dataclass that holds an application status notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="status", disp="st."),
        ]
    )

    status: StatusType = StatusType.Bootloader


@dataclass
class PayloadOTAStartAckNotification(Payload):
    """Dataclass that holds an application OTA start ACK notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: []
    )


@dataclass
class PayloadOTAChunkAckNotification(Payload):
    """Dataclass that holds an application OTA chunk ACK notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="index", disp="idx", length=4),
            PayloadFieldMetadata(name="hashes_match", disp="match"),
        ]
    )

    index: int = 0
    hashes_match: int = 0


@dataclass
class PayloadEventNotification(Payload):
    """Dataclass that holds an event notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="timestamp", disp="ts", length=4),
            PayloadFieldMetadata(name="count", disp="len."),
            PayloadFieldMetadata(
                name="data", disp="data", type_=bytes, length=0
            ),
        ]
    )

    timestamp: int = 0
    count: int = 0
    data: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadMessage(Payload):
    """Dataclass that holds a message packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="count", disp="len."),
            PayloadFieldMetadata(
                name="message", disp="msg", type_=bytes, length=0
            ),
        ]
    )

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
        SwarmitPayloadType.SWARMIT_REQUEST_RESET, PayloadResetRequest
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
