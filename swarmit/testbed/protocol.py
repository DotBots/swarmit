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


@dataclass(frozen=True)
class BatteryProfile:
    """How one robot's pack maps voltage onto remaining charge.

    Per device type because the pack differs. The v3 runs a supercapacitor:
    stored energy goes as V^2, and the robot browns out at `empty_mv` rather
    than at zero.

    `full_mv` and `warning_mv` mirror `BATTERY_VOLTAGE_FULL` /
    `BATTERY_VOLTAGE_WARNING` in device/bootloader/Source/main.c, which drives
    the status LED off the same two numbers. They must stay in step.
    """

    max_mv: int  # the 100% reference
    empty_mv: int  # 0%: below this the robot does not run
    full_mv: int  # at or above this the reading shows as full
    warning_mv: int  # below this the reading shows as critical
    supercap: bool = False  # energy goes as V^2 rather than as V


# v3: 3.0 V supercapacitor, brownout at 0.6 V.
_DOTBOT_V3_BATTERY = BatteryProfile(
    max_mv=3000, empty_mv=600, full_mv=2900, warning_mv=1500, supercap=True
)

# Everything else keeps the historical straight-voltage reading. DotBotV2 is
# battery-backed and wants its own profile, but its real full/empty voltages
# have not been measured.
_DEFAULT_BATTERY = BatteryProfile(
    max_mv=3000, empty_mv=0, full_mv=2900, warning_mv=1500
)

BATTERY_PROFILES = {
    DeviceType.DotBotV3: _DOTBOT_V3_BATTERY,
}


def battery_profile(device: DeviceType) -> BatteryProfile:
    return BATTERY_PROFILES.get(device, _DEFAULT_BATTERY)


def battery_pct(device: DeviceType, battery_mv: int) -> int:
    """Charge remaining, 0-100, on the profile for this robot."""
    p = battery_profile(device)
    if p.supercap:
        # A capacitor stores energy as 1/2 C V^2, so the usable fraction is the
        # span between the squares, not between the voltages.
        num = battery_mv**2 - p.empty_mv**2
        den = p.max_mv**2 - p.empty_mv**2
    else:
        num = battery_mv - p.empty_mv
        den = p.max_mv - p.empty_mv
    if den <= 0:
        return 0
    return max(0, min(100, int(num / den * 100)))


def battery_level(device: DeviceType, battery_mv: int) -> str:
    """Band the reading falls in: full, ok or low."""
    p = battery_profile(device)
    if battery_mv > p.full_mv:
        return "full"
    if battery_mv > p.warning_mv:
        return "ok"
    return "low"


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
    # Block-OTA (fast OTA) additions. Host -> device: report request and
    # finalize; device -> host: report response and finalize response.
    SWARMIT_OTA_BLOCK_REPORT_REQ = 0x8A
    SWARMIT_OTA_BLOCK_REPORT_RESP = 0x8B
    SWARMIT_OTA_FINALIZE = 0x8C
    SWARMIT_OTA_FINALIZE_RESP = 0x8D
    # Generic one-shot query and the one reply it can currently ask for.
    SWARMIT_REQUEST_MESSAGE = 0x8E
    SWARMIT_DEVICE_INFO_RESP = 0x8F

    # Custom messages
    SWARMIT_MESSAGE = 0xA0

    # SwarmIT calibration data
    SWARMIT_LH2_CALIBRATION = 0xA1
    # Host -> node: trigger a raw LH2 capture (READY mode only). DEPRECATED: the
    # calibrate app's button capture replaces it.
    SWARMIT_LH2_CAPTURE = 0xA2

    # Marilib metrics probe
    METRICS_PROBE = MariDefaultPayloadType.METRICS_PROBE


# Destination that reaches every node on the network.
BROADCAST_ADDRESS = 0xFFFFFFFFFFFFFFFF


# OTA protocol version a bootloader reports in its OTA_START_ACK. Version 1 is
# the retired per-chunk stop-and-wait path: it sent no version byte, so an ack
# from such a bootloader parses as 1. Version 2 is the block/bitmap path. A bot
# that does not report 2 cannot be flashed over the air any more.
OTA_PROTOCOL_VERSION_LEGACY = 1
OTA_PROTOCOL_VERSION_BLOCK = 2


# First byte of a raw LH2 capture sample carried inside a SWARMIT_EVENT_LOG
# payload. Mirrors SWRMT_LH2_CALIB_TAG in the swarmit bootloader firmware; lets
# the host tell a calibration sample apart from a regular text log line. Each
# sample that follows is [lh_index:1][count1:4 LE][count2:4 LE]. DEPRECATED
# with SWARMIT_LH2_CAPTURE, whose reply it tags.
LH2_CALIB_TAG = 0xCA


class FaultType(Enum):
    """Fault latched by the bootloader before the reset."""

    NoFault = 0
    HardFault = 1
    SecureFault = 2
    # No fault was raised: WDT0 timed out because the application stopped
    # reloading it. pc/lr name where it was stuck; cfsr/sfsr are structurally
    # zero, so the inspect view skips them for this one.
    WatchdogTimeout = 3


# nRF5340 application core RESETREAS flags (bit position -> short label).
RESET_REASON_FLAGS = {
    1 << 0: "pin",
    1 << 1: "watchdog0",
    1 << 2: "ctrl-ap",
    1 << 3: "soft-reset",
    1 << 4: "lockup",
    1 << 5: "off-wakeup",
    1 << 6: "lpcomp",
    1 << 7: "debug-if",
    1 << 24: "nfc",
    1 << 25: "watchdog1",
    1 << 26: "vbus",
}


def decode_reset_reason(reset_reason: int) -> str:
    """Decode a RESETREAS register value into a short readable string."""
    if reset_reason == 0:
        return "power-on"
    labels = [
        label
        for mask, label in RESET_REASON_FLAGS.items()
        if reset_reason & mask
    ]
    unknown = reset_reason & ~sum(RESET_REASON_FLAGS)
    if unknown:
        labels.append(f"0x{unknown:08x}")
    return "+".join(labels)


# ARMv8-M Configurable Fault Status Register (CFSR) bits: MMFSR (0-7),
# BFSR (8-15), UFSR (16-31). Used by the inspect command to spell out the
# raw fault status the bootloader latched.
CFSR_FLAGS = {
    1 << 0: "IACCVIOL",
    1 << 1: "DACCVIOL",
    1 << 3: "MUNSTKERR",
    1 << 4: "MSTKERR",
    1 << 5: "MLSPERR",
    1 << 8: "IBUSERR",
    1 << 9: "PRECISERR",
    1 << 10: "IMPRECISERR",
    1 << 11: "UNSTKERR",
    1 << 12: "STKERR",
    1 << 13: "LSPERR",
    1 << 16: "UNDEFINSTR",
    1 << 17: "INVSTATE",
    1 << 18: "INVPC",
    1 << 19: "NOCP",
    1 << 20: "STKOF",
    1 << 24: "UNALIGNED",
    1 << 25: "DIVBYZERO",
}

# ARMv8-M Secure Fault Status Register (SFSR) bits.
SFSR_FLAGS = {
    1 << 0: "INVEP",
    1 << 1: "INVIS",
    1 << 2: "INVER",
    1 << 3: "AUVIOL",
    1 << 4: "INVTRAN",
    1 << 5: "LSPERR",
    1 << 6: "SFARVALID",
    1 << 7: "LSERR",
}


def _decode_flags(value: int, flags: dict[int, str]) -> str:
    if value == 0:
        return ""
    return "+".join(label for mask, label in flags.items() if value & mask)


def decode_cfsr(cfsr: int) -> str:
    """Decode a CFSR value into its set fault-status flag names."""
    return _decode_flags(cfsr, CFSR_FLAGS)


def decode_sfsr(sfsr: int) -> str:
    """Decode an SFSR value into its set secure-fault flag names."""
    return _decode_flags(sfsr, SFSR_FLAGS)


# ARMv8-M exception numbers, as they appear in xPSR's IPSR field. Numbers at or
# above 16 are external interrupts, IRQ = number - 16.
IPSR_EXCEPTIONS = {
    0: "thread",
    2: "NMI",
    3: "HardFault",
    4: "MemManage",
    5: "BusFault",
    6: "UsageFault",
    7: "SecureFault",
    11: "SVCall",
    12: "DebugMonitor",
    14: "PendSV",
    15: "SysTick",
}


def decode_ipsr(psr: int) -> str:
    """Name the exception the interrupted context was running in.

    IPSR is the low 9 bits of xPSR. `thread` means ordinary application code;
    anything else means the hang or fault happened inside a handler, which is
    the one thing this field tells you that the pc alone does not - a pc in a
    driver function reads the same either way.
    """
    number = psr & 0x1FF
    if number in IPSR_EXCEPTIONS:
        return IPSR_EXCEPTIONS[number]
    if number >= 16:
        return f"IRQ {number - 16}"
    return f"exception {number}"


# The fixed head of the status payload: device, status, battery, position.
STATUS_BASE_SIZE = 12
# Size of the crash report appended to status payloads (mirrors
# ipc_crash_report_t in the swarmit firmware).
CRASH_REPORT_SIZE = 30
# Size of the generation counter appended after the crash report.
INFO_GEN_SIZE = 1

# Width of the identity strings on the wire, NUL-padded. Mirrors
# SWRMT_INFO_STRING_LEN in the firmware; Matter, Zigbee and Thread all cap
# identity strings at 32 bytes and this follows them.
INFO_STRING_LEN = 32
# Bytes of the image SHA256 carried on the wire (the device keeps all 32).
IMAGE_DIGEST_LEN = 8
# Schema version this host understands in SWARMIT_DEVICE_INFO_RESP. A bot
# reporting an older one runs firmware to reflash.
DEVICE_INFO_VERSION = 2
# The LH2 site name and calibration id, as the calibration message, the
# config page and device info v2 carry them.
LH2_SITE_NAME_LEN = 16
LH2_CALIBRATION_ID_LEN = 8


class ImageState(Enum):
    """Image lifecycle. LwM2M Object 5 resource 3 (State)."""

    Idle = 0
    Downloading = 1
    Downloaded = 2
    Updating = 3


class ImageResult(Enum):
    """Outcome of the last transfer. LwM2M Object 5 resource 5."""

    Initial = 0
    Success = 1
    NotEnoughFlash = 2
    ConnectionLost = 4
    IntegrityCheckFailure = 5
    UpdateFailed = 8


class BootReason(Enum):
    """Why the device last booted. Matter BootReasonEnum (cluster 0x0033).

    Derived on the host by `boot_reason()` rather than sent by the device:
    everything it needs - RESETREAS and the latched fault - already rides the
    status frame, so putting the mapping on the wire would duplicate a fact and
    make correcting it a firmware flash.
    """

    Unspecified = 0
    PowerOnReboot = 1
    BrownOutReset = 2
    SoftwareWatchdogReset = 3
    HardwareWatchdogReset = 4
    SoftwareUpdateCompleted = 5
    SoftwareReset = 6


# RESETREAS bits with a swarmit-specific meaning. WDT0 is the crash deadman a
# running app must pet; WDT1 is started by the stop command's DPPI path and by
# nothing else.
_RR_PIN = 1 << 0
_RR_WDT0 = 1 << 1
_RR_SREQ = 1 << 3
_RR_LOCKUP = 1 << 4
_RR_WDT1 = 1 << 25


def boot_reason(reset_reason: int, fault: int) -> BootReason:
    """Map RESETREAS + the latched fault onto Matter's BootReasonEnum.

    Coarse by construction - the enum has no value for a CPU lockup, and the
    raw register in the status frame stays the authoritative answer. Order
    matters: a cabled flash sets ctrl-ap, SREQ and LOCKUP at once, and of those
    a commanded reset is what actually happened, so SREQ is tested before
    LOCKUP. Reporting a freshly programmed device as watchdog-reset tells an
    operator something went wrong when nothing did.
    """
    # A crash wins: the fault handler latches and then hangs until WDT0 fires,
    # so both can be set. WDT0 is a real watchdog, so this is the one case that
    # honestly maps to a watchdog value.
    if fault or (reset_reason & _RR_WDT0):
        return BootReason.HardwareWatchdogReset
    # Only the stop command starts WDT1, so that is a commanded reset.
    if reset_reason & _RR_WDT1:
        return BootReason.SoftwareReset
    if reset_reason & _RR_SREQ:
        return BootReason.SoftwareReset
    if reset_reason == 0 or (reset_reason & _RR_PIN):
        return BootReason.PowerOnReboot
    return BootReason.Unspecified


# Bits of the lh2_flags field.
LH2_FLAG_VALID = 1 << 0
LH2_FLAG_FROM_FLASH = 1 << 1


def decode_string_field(raw: bytes) -> str:
    """Decode a NUL-padded fixed-width identity string off the wire."""
    return bytes(raw).split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def encode_string_field(value: str, length: int = INFO_STRING_LEN) -> bytes:
    """Encode a string into a fixed-width NUL-padded field.

    Truncates at length - 1 so the field always ends NUL-terminated, which is
    what the firmware's fixed-width char arrays assume.
    """
    raw = (value or "").encode("utf-8")[: length - 1]
    return raw + bytes(length - len(raw))


# Requests
@dataclass
class PayloadStatus(Payload):
    """Dataclass that holds an application status notification packet."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="device", disp="dev."),
            PayloadFieldMetadata(name="status", disp="st."),
            PayloadFieldMetadata(name="battery", disp="bat.", length=2),
            PayloadFieldMetadata(name="pos_x", disp="pos x", length=4),
            PayloadFieldMetadata(name="pos_y", disp="pos y", length=4),
            # Crash report. Inventory rather than state - latched once at boot
            # and unchanged for the rest of the run - so by the split rule that
            # sends image and firmware versions on request instead, it does not
            # belong in a 1 Hz frame. It stays because a crash report is wanted
            # exactly when a bot is unhealthy and barely reachable, and this
            # frame lands where a 156-byte on-request reply does not. Not for
            # airtime: a Mari slot costs the same whatever the payload length.
            PayloadFieldMetadata(name="reset_reason", disp="rst", length=4),
            PayloadFieldMetadata(name="fault", disp="fault"),
            PayloadFieldMetadata(name="from_ns", disp="ns"),
            PayloadFieldMetadata(name="cfsr", disp="cfsr", length=4),
            PayloadFieldMetadata(name="sfsr", disp="sfsr", length=4),
            PayloadFieldMetadata(name="pc", disp="pc", length=4),
            PayloadFieldMetadata(name="lr", disp="lr", length=4),
            PayloadFieldMetadata(name="sp", disp="sp", length=4),
            PayloadFieldMetadata(name="psr", disp="psr", length=4),
            PayloadFieldMetadata(name="info_gen", disp="gen"),
        ]
    )

    device: DeviceType = DeviceType.Unknown
    status: StatusType = StatusType.Bootloader
    battery: int = 0
    pos_x: int = 0
    pos_y: int = 0
    reset_reason: int = 0
    fault: int = 0
    from_ns: int = 0
    cfsr: int = 0
    sfsr: int = 0
    pc: int = 0
    lr: int = 0
    sp: int = 0
    psr: int = 0
    # Changes whenever anything in the device-info block changes. The
    # controller refetches on any difference from what it cached, so the
    # steady state costs no device-info traffic at all.
    info_gen: int = 0

    # There is deliberately no upgrade path for a shorter frame. Firmware and
    # host ship together, so a payload of any other shape comes from a bot too
    # old to talk to: the adapter drops the frame and the bot never appears,
    # which is the wanted outcome. Reflashing is the fix, and `swarm flash`
    # already refuses those bots by bootloader version.


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
class PayloadLH2Capture(PayloadEmpty):
    """Dataclass that holds a raw LH2 capture trigger (no body)."""


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
    """Dataclass that holds an OTA start packet.

    Everything after the first 8 bytes (image size + chunk count) was appended
    later. The device reads this with a pointer cast and checks the received
    length, so an older bootloader ignores the tail and a newer one treats a
    short packet as "name and version not sent".
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="fw_length", disp="len.", length=4),
            PayloadFieldMetadata(
                name="fw_chunk_counts", disp="chunks", length=4
            ),
            PayloadFieldMetadata(name="version", disp="ver.", length=1),
            PayloadFieldMetadata(
                name="image_name",
                disp="name",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
            PayloadFieldMetadata(
                name="image_version",
                disp="img ver.",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
        ]
    )

    fw_length: int = 0
    fw_chunk_count: int = 0
    version: int = OTA_PROTOCOL_VERSION_BLOCK
    image_name: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )
    image_version: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )

    def __post_init__(self):
        # Accept plain strings at the call site and normalise to the
        # fixed-width NUL-padded form the wire and the firmware expect.
        if isinstance(self.image_name, str):
            self.image_name = encode_string_field(self.image_name)
        if isinstance(self.image_version, str):
            self.image_version = encode_string_field(self.image_version)


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
class PayloadCalibrationData(Payload):
    """One station's LH2 homography, `swrmt_lh2_calibration_data_t`.

    The matrix is nine little-endian float32, row-major. The validity
    rectangle, site name and calibration id are the same in every message of
    one push.
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(
                name="homography_count", disp="count", length=4
            ),
            PayloadFieldMetadata(
                name="homography_index", disp="idx", length=4
            ),
            PayloadFieldMetadata(
                name="homography", type_=bytes, length=3 * 3 * 4
            ),
            PayloadFieldMetadata(name="valid_x_min", disp="x0", length=4),
            PayloadFieldMetadata(name="valid_y_min", disp="y0", length=4),
            PayloadFieldMetadata(name="valid_x_max", disp="x1", length=4),
            PayloadFieldMetadata(name="valid_y_max", disp="y1", length=4),
            PayloadFieldMetadata(
                name="site_name",
                disp="site",
                type_=bytes,
                length=LH2_SITE_NAME_LEN,
            ),
            PayloadFieldMetadata(
                name="calibration_id",
                disp="id",
                type_=bytes,
                length=LH2_CALIBRATION_ID_LEN,
            ),
        ]
    )

    homography_count: int = 0
    homography_index: int = 0
    homography: bytes = dataclasses.field(default_factory=lambda: bytes(36))
    valid_x_min: int = 0
    valid_y_min: int = 0
    valid_x_max: int = 0
    valid_y_max: int = 0
    site_name: bytes = dataclasses.field(
        default_factory=lambda: bytes(LH2_SITE_NAME_LEN)
    )
    calibration_id: bytes = dataclasses.field(
        default_factory=lambda: bytes(LH2_CALIBRATION_ID_LEN)
    )

    @property
    def site_fields(self) -> tuple:
        """The validity rectangle, site name and id, identical across one push."""
        return (
            self.valid_x_min,
            self.valid_y_min,
            self.valid_x_max,
            self.valid_y_max,
            self.site_name,
            self.calibration_id,
        )


@dataclass
class PayloadOTAStartAck(Payload):
    """Dataclass that holds an application OTA start ACK notification packet.

    A block-OTA bootloader appends its `version` byte; a legacy bootloader
    sends the empty ack, which parses as version 1.
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="version", disp="ver.", length=1),
        ]
    )

    version: int = OTA_PROTOCOL_VERSION_LEGACY

    def from_bytes(self, bytes_):
        # Legacy bootloaders send an empty ack (no version byte); treat that
        # as version 1 so mixed fleets negotiate correctly.
        if len(bytes_) == 0:
            self.version = OTA_PROTOCOL_VERSION_LEGACY
            return self
        return super().from_bytes(bytes_)


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
class PayloadOTABlockReportReq(Payload):
    """Host -> device: request a bot's received-chunk bitmap for one block.

    The device answers with the block it currently holds, not necessarily the
    one asked about - the fields say which block prompted the request and how
    wide it is, and a device on an older block is read as needing all of it.
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="block_index", disp="blk", length=4),
            PayloadFieldMetadata(name="block_size", disp="w"),
        ]
    )

    block_index: int = 0
    block_size: int = 0


@dataclass
class PayloadOTABlockReportResp(Payload):
    """Device -> host: bitmap of received+verified chunks for its block.

    `block_index` is the block the bot currently holds; a bot that has not yet
    written any chunk of the requested block reports an earlier block, which the
    controller reads as "needs the whole requested block".
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="block_index", disp="blk", length=4),
            PayloadFieldMetadata(name="received_mask", disp="mask", length=4),
            PayloadFieldMetadata(name="status", disp="st."),
        ]
    )

    block_index: int = 0
    received_mask: int = 0
    status: int = 0


@dataclass
class PayloadOTAFinalize(Payload):
    """Host -> device: verify the whole written image against this SHA256."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="sha", type_=bytes, length=32),
        ]
    )

    sha: bytes = dataclasses.field(default_factory=lambda: bytearray)


@dataclass
class PayloadOTAFinalizeResp(Payload):
    """Device -> host: 1 if the image SHA256 matched, 0 otherwise."""

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="ok", disp="ok"),
        ]
    )

    ok: int = 0


@dataclass
class PayloadRequestMessage(Payload):
    """Host -> device: emit one message, once.

    Generic on purpose. MAVLink replaced ~15 bespoke MAV_CMD_REQUEST_*
    commands with a single MAV_CMD_REQUEST_MESSAGE, so a future query here
    adds a `msg_id` rather than another request/response pair.
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="msg_id", disp="msg"),
            PayloadFieldMetadata(name="flags", disp="fl."),
        ]
    )

    msg_id: int = PayloadType.SWARMIT_DEVICE_INFO_RESP
    flags: int = 0


@dataclass
class PayloadDeviceInfo(Payload):
    """Device -> host: what this bot is running.

    Read once and cached; refreshed only when the status frame's `info_gen`
    stops matching the value this reply carried.
    """

    metadata: list[PayloadFieldMetadata] = dataclasses.field(
        default_factory=lambda: [
            PayloadFieldMetadata(name="info_version", disp="v"),
            PayloadFieldMetadata(name="info_gen", disp="gen"),
            PayloadFieldMetadata(name="boot_count", disp="boots", length=4),
            PayloadFieldMetadata(name="uptime_s", disp="up", length=4),
            PayloadFieldMetadata(
                name="bl_version",
                disp="bl",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
            PayloadFieldMetadata(
                name="net_version",
                disp="net",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
            PayloadFieldMetadata(name="image_state", disp="st."),
            PayloadFieldMetadata(name="image_result", disp="res."),
            PayloadFieldMetadata(name="image_size", disp="size", length=4),
            PayloadFieldMetadata(
                name="image_digest",
                disp="digest",
                type_=bytes,
                length=IMAGE_DIGEST_LEN,
            ),
            PayloadFieldMetadata(
                name="image_name",
                disp="name",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
            PayloadFieldMetadata(
                name="image_version",
                disp="ver.",
                type_=bytes,
                length=INFO_STRING_LEN,
            ),
            PayloadFieldMetadata(name="lh2_homography_count", disp="lh2"),
            PayloadFieldMetadata(name="lh2_flags", disp="lh2f"),
            PayloadFieldMetadata(
                name="lh2_site_name",
                disp="site",
                type_=bytes,
                length=LH2_SITE_NAME_LEN,
            ),
            PayloadFieldMetadata(
                name="lh2_calibration_id",
                disp="cal.",
                type_=bytes,
                length=LH2_CALIBRATION_ID_LEN,
            ),
        ]
    )

    info_version: int = 0
    info_gen: int = 0
    boot_count: int = 0
    uptime_s: int = 0
    bl_version: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )
    net_version: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )
    image_state: int = 0
    image_result: int = 0
    image_size: int = 0
    image_digest: bytes = dataclasses.field(
        default_factory=lambda: bytes(IMAGE_DIGEST_LEN)
    )
    image_name: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )
    image_version: bytes = dataclasses.field(
        default_factory=lambda: bytes(INFO_STRING_LEN)
    )
    lh2_homography_count: int = 0
    lh2_flags: int = 0
    lh2_site_name: bytes = dataclasses.field(
        default_factory=lambda: bytes(LH2_SITE_NAME_LEN)
    )
    lh2_calibration_id: bytes = dataclasses.field(
        default_factory=lambda: bytes(LH2_CALIBRATION_ID_LEN)
    )

    def from_bytes(self, bytes_):
        """Parse a reply; one older than DEVICE_INFO_VERSION keeps only its
        version and generation, enough to tell the operator to reflash."""
        if len(bytes_) >= 2 and 0 < bytes_[0] < DEVICE_INFO_VERSION:
            self.info_version, self.info_gen = bytes_[0], bytes_[1]
            return self
        return super().from_bytes(bytes_)


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
register_parser(
    PayloadType.SWARMIT_OTA_BLOCK_REPORT_REQ, PayloadOTABlockReportReq
)
register_parser(
    PayloadType.SWARMIT_OTA_BLOCK_REPORT_RESP, PayloadOTABlockReportResp
)
register_parser(PayloadType.SWARMIT_OTA_FINALIZE, PayloadOTAFinalize)
register_parser(PayloadType.SWARMIT_OTA_FINALIZE_RESP, PayloadOTAFinalizeResp)
register_parser(PayloadType.SWARMIT_REQUEST_MESSAGE, PayloadRequestMessage)
register_parser(PayloadType.SWARMIT_DEVICE_INFO_RESP, PayloadDeviceInfo)
register_parser(PayloadType.SWARMIT_EVENT_LOG, PayloadEvent)
register_parser(PayloadType.SWARMIT_MESSAGE, PayloadMessage)
register_parser(PayloadType.SWARMIT_LH2_CALIBRATION, PayloadCalibrationData)
register_parser(PayloadType.SWARMIT_LH2_CAPTURE, PayloadLH2Capture)
register_parser(PayloadType.METRICS_PROBE, MetricsProbePayload)
