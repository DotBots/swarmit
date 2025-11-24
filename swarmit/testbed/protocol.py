"""Swarmit protocol definition."""

import dataclasses
from dataclasses import dataclass
from enum import Enum, IntEnum

from dotbot_utils.protocol import (
    Payload,
    PayloadFieldMetadata,
    register_parser,
)
from marilib.mari_protocol import DefaultPayloadType as MariDefaultPayloadType
from marilib.mari_protocol import MetricsProbePayload


class StatusType(Enum):
    """Types of device status."""

    Bootloader = 0
    Running = 1
    Stopping = 2
    Resetting = 3
    Programming = 4


class DeviceType(Enum):
    """Types of devices."""

    Unknown = 0
    DotBotV3 = 1
    DotBotV2 = 2
    nRF5340DK = 3
    nRF52840DK = 4


class PayloadType(IntEnum):
    """Types of DotBot payload types."""

    # Requests
    SWARMIT_STATUS = 0x80
    SWARMIT_START = 0x81
    SWARMIT_STOP = 0x82
    SWARMIT_RESET = 0x83
    SWARMIT_OTA_START = 0x84
    SWARMIT_OTA_CHUNK = 0x85
    SWARMIT_OTA_START_ACK = 0x86
    SWARMIT_OTA_CHUNK_ACK = 0x87
    SWARMIT_EVENT_GPIO = 0x88
    SWARMIT_EVENT_LOG = 0x89

    # Custom messages
    SWARMIT_MESSAGE = 0xA0

    # Marilib metrics probe
    METRICS_PROBE = MariDefaultPayloadType.METRICS_PROBE


# Requests
@dataclass
class PayloadStatus(Payload):
    """Dataclass that holds an application status notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="device", disp="dev."),
            PayloadFieldMetadata(name="status", disp="st."),
            PayloadFieldMetadata(name="battery", disp="bat.", length=2),
            PayloadFieldMetadata(
                name="pos_x", disp="pos x", length=4, signed=True
            ),
            PayloadFieldMetadata(
                name="pos_y", disp="pos y", length=4, signed=True
            ),
        ]
    )

    device: DeviceType = DeviceType.Unknown
    status: StatusType = StatusType.Bootloader
    battery: int = 0
    pos_x: int = 0
    pos_y: int = 0


@dataclass
class PayloadEmpty(Payload):
    """Dataclass that holds an application request packet (start/stop/status)."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: []
    )


@dataclass
class PayloadStart(PayloadEmpty):
    """Dataclass that holds an application start request packet."""


@dataclass
class PayloadStop(PayloadEmpty):
    """Dataclass that holds an application stop request packet."""


@dataclass
class PayloadReset(Payload):
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
class PayloadOTAStart(Payload):
    """Dataclass that holds an OTA start packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="fw_length", disp="len.", length=4),
            PayloadFieldMetadata(
                name="fw_chunk_counts", disp="chunks", length=4
            ),
        ]
    )

    fw_length: int = 0
    fw_chunk_count: int = 0


@dataclass
class PayloadOTAChunk(Payload):
    """Dataclass that holds an OTA chunk packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="index", disp="idx", length=4),
            PayloadFieldMetadata(name="count", disp="size"),
            PayloadFieldMetadata(name="sha", type_=bytes, length=8),
            PayloadFieldMetadata(name="chunk", type_=bytes, length=0),
        ]
    )

    index: int = 0
    count: int = 0
    sha: bytes = dataclasses.field(default_factory=lambda: bytearray)
    chunk: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadOTAStartAck(Payload):
    """Dataclass that holds an application OTA start ACK notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: []
    )


@dataclass
class PayloadOTAChunkAck(Payload):
    """Dataclass that holds an application OTA chunk ACK notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="index", disp="idx", length=4),
        ]
    )

    index: int = 0


@dataclass
class PayloadEvent(Payload):
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


# Register all swarmit specific parsers at module level
register_parser(PayloadType.SWARMIT_STATUS, PayloadStatus)
register_parser(PayloadType.SWARMIT_START, PayloadStart)
register_parser(PayloadType.SWARMIT_STOP, PayloadStop)
register_parser(PayloadType.SWARMIT_RESET, PayloadReset)
register_parser(PayloadType.SWARMIT_OTA_START, PayloadOTAStart)
register_parser(PayloadType.SWARMIT_OTA_CHUNK, PayloadOTAChunk)
register_parser(PayloadType.SWARMIT_OTA_START_ACK, PayloadOTAStartAck)
register_parser(PayloadType.SWARMIT_OTA_CHUNK_ACK, PayloadOTAChunkAck)
register_parser(PayloadType.SWARMIT_EVENT_LOG, PayloadEvent)
register_parser(PayloadType.SWARMIT_MESSAGE, PayloadMessage)
register_parser(PayloadType.METRICS_PROBE, MetricsProbePayload)
