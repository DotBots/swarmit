"""Module containing the swarmit controller class."""

import dataclasses
import os
import threading
import time
from binascii import hexlify
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from dotbot_utils.protocol import Packet, Payload
from dotbot_utils.serial_interface import get_default_port
from rich import get_console, print
from rich.columns import Columns
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from tqdm import tqdm

from swarmit.testbed.adapter import (
    DEVICE_CHUNK_RATE_HZ,
    OTA_DOWNLINK_UTILIZATION,
    GatewayAdapterBase,
    LinkGeometry,
    MarilibCloudAdapter,
    MarilibEdgeAdapter,
    derive_block_settings,
)
from swarmit.testbed.logger import LOGGER
from swarmit.testbed.ota import BLOCK_SIZE_DEFAULT, BlockTransfer
from swarmit.testbed.protocol import (
    _RR_LOCKUP,
    _RR_PIN,
    _RR_SREQ,
    _RR_WDT0,
    _RR_WDT1,
    BROADCAST_ADDRESS,
    DEVICE_INFO_VERSION,
    LH2_FLAG_FROM_FLASH,
    LH2_FLAG_VALID,
    OTA_PROTOCOL_VERSION_BLOCK,
    OTA_PROTOCOL_VERSION_LEGACY,
    DeviceType,
    FaultType,
    ImageResult,
    ImageState,
    PayloadCalibrationData,
    PayloadLH2Capture,
    PayloadMessage,
    PayloadOTAStart,
    PayloadRequestMessage,
    PayloadReset,
    PayloadStart,
    PayloadStop,
    PayloadType,
    StatusType,
    battery_level,
    battery_pct,
    decode_cfsr,
    decode_ipsr,
    decode_reset_reason,
    decode_sfsr,
    decode_string_field,
)

CHUNK_SIZE = 128
COMMAND_TIMEOUT = 2
COMMAND_MAX_ATTEMPTS = 5
COMMAND_ATTEMPT_DELAY = 0.7
INACTIVE_TIMEOUT = 3  # s
STATUS_TIMEOUT = 2
MONITOR_TIMEOUT = 60  # s
OTA_MAX_RETRIES_DEFAULT = 10
OTA_ACK_TIMEOUT_DEFAULT = 0.7
# Shortest gap between two device-info broadcasts. One broadcast serves every
# stale bot at once - each answers in its own uplink cell - so this is a
# refresh rate for the whole fleet, not per device.
DEVICE_INFO_REFRESH_INTERVAL = 2.0  # s
# Ceiling on the retry interval for a device that should answer and has not.
# There is deliberately no attempt cap: firmware that cannot answer is
# identified by a zero generation counter and never asked at all, so the only
# devices reaching this path are ones that should reply - typically busy
# carrying a running user image. Giving up on those would leave them showing
# as unknown until something else moved their counter, so they are asked less
# often instead of not at all. At the ceiling this is 0.03 requests a second
# for the whole fleet.
DEVICE_INFO_BACKOFF_MAX = 30.0  # s
# How long `info` waits for replies when it asks explicitly, and how often it
# re-asks inside that window. Wide enough to survive a bot whose uplink cell is
# busy carrying a running user image, which one request inside 1.5 s was not.
DEVICE_INFO_TIMEOUT = 4.0  # s
DEVICE_INFO_RESEND_INTERVAL = 0.6  # s
SERIAL_PORT_DEFAULT = get_default_port()
VOLTAGE_MAX = 3000  # mV
VOLTAGE_FULL = 2900  # mV
VOLTAGE_WARNING = 1500  # mV


def _test_drop_chunks() -> set[int]:
    """Chunk indices to silently never transmit (fault injection).

    Set SWARMIT_OTA_TEST_DROP=200,201 to prove the finalize SHA256 rejects an
    incomplete image. This is a test seam, not configuration, which is why it
    lives in the environment and not in the settings file.
    """
    raw = os.environ.get("SWARMIT_OTA_TEST_DROP", "")
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}


class StaleBootloaderError(Exception):
    """Raised when a target bot's bootloader predates the block OTA protocol.

    Such a bot only speaks the retired per-chunk protocol, so it cannot be
    flashed over the air. Re-provision it over J-Link with
    ``dotbot device flash-swarmit-sandbox``.
    """

    def __init__(self, devices):
        self.devices = list(devices)
        super().__init__(
            f"{len(self.devices)} device(s) run a bootloader older than the "
            f"block OTA protocol: {', '.join(self.devices)}. Re-provision "
            "them with 'dotbot device flash-swarmit-sandbox'."
        )


@dataclass
class DeviceInfo:
    """What a bot reports it is running, decoded for display.

    Fetched once and cached; refreshed only when the status frame's
    generation counter stops matching `info_gen`.
    """

    info_version: int = 0
    info_gen: int = 0
    boot_count: int = 0
    uptime_s: int = 0
    bl_version: str = ""
    net_version: str = ""
    image_state: int = 0
    image_result: int = 0
    image_size: int = 0
    image_digest: str = ""  # hex, first 8 bytes of the image SHA256
    image_name: str = ""
    image_version: str = ""
    lh2_homography_count: int = 0
    lh2_flags: int = 0
    raw: str = ""  # hex of the full device-info packet as received

    @classmethod
    def from_payload(cls, payload, raw: str = "") -> "DeviceInfo":
        return cls(
            raw=raw,
            info_version=payload.info_version,
            info_gen=payload.info_gen,
            boot_count=payload.boot_count,
            uptime_s=payload.uptime_s,
            bl_version=decode_string_field(payload.bl_version),
            net_version=decode_string_field(payload.net_version),
            image_state=payload.image_state,
            image_result=payload.image_result,
            image_size=payload.image_size,
            image_digest=bytes(payload.image_digest).hex(),
            image_name=decode_string_field(payload.image_name),
            image_version=decode_string_field(payload.image_version),
            lh2_homography_count=payload.lh2_homography_count,
            lh2_flags=payload.lh2_flags,
        )

    @property
    def has_image(self) -> bool:
        """Whether the device carries a user image at all.

        A device that has never been flashed over the air reports a zeroed
        record, so an all-zero digest means "no image" rather than "an image
        whose digest happens to be zero".
        """
        return self.image_size > 0 or self.image_digest.strip("0") != ""

    @property
    def image_label(self) -> str:
        """How to name this image in a table.

        The digest is the identity; the name is decoration that a device
        flashed by an older controller simply does not have. Falling back to
        the digest keeps the column meaningful either way. Note the three
        outcomes are distinct and all worth telling apart: a name, a bare
        digest, and `none` for a device that answered and has no image - which
        is not the same as the `-` shown for one that never answered.
        """
        if not self.has_image:
            return "none"
        return self.image_name or self.image_digest[:16] or "-"

    @property
    def image_state_name(self) -> str:
        try:
            return ImageState(self.image_state).name
        except ValueError:
            return f"state{self.image_state}"

    @property
    def image_result_name(self) -> str:
        try:
            return ImageResult(self.image_result).name
        except ValueError:
            return f"result{self.image_result}"

    @property
    def lh2_summary(self) -> str:
        if not self.lh2_homography_count:
            return "uncalibrated"
        # One homography is stored per basestation index, so the count is the
        # number of lighthouses - which is what an operator can check against
        # the room, where "homographies" needs translating first.
        noun = (
            "basestation" if self.lh2_homography_count == 1 else "basestations"
        )
        flags = []
        if self.lh2_flags & LH2_FLAG_VALID:
            flags.append("valid")
        if self.lh2_flags & LH2_FLAG_FROM_FLASH:
            flags.append("from flash")
        suffix = f" ({', '.join(flags)})" if flags else ""
        return f"{self.lh2_homography_count} {noun}{suffix}"


@dataclass
class NodeStatus:
    """Class that holds node status."""

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
    raw: str = ""  # hex of the full status packet as received
    last_updated_at: float = 0
    # Generation counter as of the most recent status frame. When it differs
    # from `info.info_gen` the cached block is stale and gets refetched.
    info_gen: int = 0
    info: DeviceInfo | None = None


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
    fw_hash: bytes = b""
    addrs: list[str] = dataclasses.field(default_factory=lambda: [])
    retries: int = 0


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


def battery_level_color(device_data):
    """Rich colour for the reading, on this robot's own battery profile."""
    return {"full": "cyan", "ok": "green", "low": "red"}[
        battery_level(device_data.device, device_data.battery)
    ]


def fault_name(device_data) -> str:
    """Name of the latched fault, or a placeholder for an unknown code."""
    try:
        return FaultType(device_data.fault).name
    except ValueError:
        return f"fault{device_data.fault}"


def reset_severity(device_data) -> str:
    """How much attention the last reset deserves: crashed, hung or normal.

    "hung" is a separate tier from "crashed" because a watchdog timeout
    raises no fault.
    """
    rr = device_data.reset_reason
    if device_data.fault or (rr & _RR_WDT0):
        if device_data.fault == FaultType.WatchdogTimeout.value:
            return "hung"
        return "crashed"
    return "normal"


def format_reset_cause(device_data) -> str:
    """Friendly one-line label for a node's last reset cause.

    Maps the raw RESETREAS + latched fault onto swarmit semantics. The raw
    values stay available in the inspect view for low-level debugging.
    """
    rr = device_data.reset_reason
    # Crash wins over everything: a stop racing a crash can set both bits.
    if device_data.fault or (rr & _RR_WDT0):
        # Surface the raw reset reason too (watchdog0 for the crash deadman,
        # lockup if the fault handler itself wedged) - it disambiguates the
        # crash path at a glance.
        reset_name = decode_reset_reason(rr)
        if device_data.fault == FaultType.WatchdogTimeout.value:
            # No fault was raised here - the application just missed its
            # deadline. Calling that "crashed" sends an operator hunting for a
            # fault that does not exist; the pc is the whole answer.
            return f"hung ({reset_name} pc=0x{device_data.pc:08x})"
        if device_data.fault:
            return (
                f"crashed ({reset_name} {fault_name(device_data)} "
                f"pc=0x{device_data.pc:08x})"
            )
        return f"crashed ({reset_name})"
    if rr & _RR_WDT1:
        return "stopped"
    if rr & _RR_LOCKUP:
        return "lockup"
    if rr == 0 or (rr & _RR_PIN):
        return "power-on"
    if rr & _RR_SREQ:
        return "soft-reset"
    return decode_reset_reason(rr)


def reset_cause_color(device_data) -> str:
    if device_data.fault or (
        device_data.reset_reason & (_RR_WDT0 | _RR_LOCKUP)
    ):
        return "red"
    return "cyan"


def _hex_dump(raw: str, width: int = 16) -> str:
    """Offset-prefixed hex, the shape nrfjprog and text2pcap both print.

    Wrapped rather than run on one line: a 156-byte device-info packet is 468
    characters, which stretches the panel to three times the width of every
    other row in it. The offsets are not decoration - they line up with the
    field offsets in doc/wire-protocol.md, so a byte can be read straight off
    the dump against the table there.
    """
    out = []
    for off in range(0, len(raw) // 2, width):
        chunk = raw[off * 2 : (off + width) * 2]
        pairs = " ".join(chunk[i : i + 2] for i in range(0, len(chunk), 2))
        out.append(f"{off:04x}  {pairs}")
    return "\n".join(out)


def format_uptime(seconds: int) -> str:
    """Uptime as the operator reads it, not as a raw second count."""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def image_mismatches(status_data) -> tuple[str, list[tuple[str, DeviceInfo]]]:
    """The fleet's majority image digest, and every device that differs.

    Comparison is on the digest, never the name: the name is display-only and
    two bots can carry the same label with different bytes. Devices that have
    not reported device info yet are not counted either way - unknown is not
    the same as different.
    """
    known = {
        addr: data.info
        for addr, data in status_data.items()
        if data.info is not None and data.info.image_digest
    }
    if len(known) < 2:
        return "", []
    counts: dict[str, int] = {}
    for info in known.values():
        counts[info.image_digest] = counts.get(info.image_digest, 0) + 1
    majority = max(counts, key=lambda digest: (counts[digest], digest))
    if counts[majority] == len(known):
        return majority, []
    odd = sorted(
        (
            (addr, info)
            for addr, info in known.items()
            if info.image_digest != majority
        ),
        key=lambda item: item[0],
    )
    return majority, odd


def _split_dirty(version: str) -> tuple[str, bool]:
    """Separate a `git describe --dirty` version from its dirty marker."""
    if version.endswith("-dirty"):
        return version[: -len("-dirty")], True
    return version, False


def format_sandbox_fw(info: DeviceInfo | None) -> str:
    """One column for the bootloader and net-core versions.

    They are built and flashed together, so the two agreeing is the normal
    case and printing both in full would spend ~50 columns on every row to
    say the same thing twice. Collapse them when they agree and show both
    when they do not - a real disagreement means a half-finished flash, which
    is the reason to have the column at all.

    `-dirty` is build state rather than a different version, so it is compared
    out and reported as a flag. Otherwise a net core built from an uncommitted
    tree - the normal case at the bench - would look like a version mismatch
    and defeat the collapse on every row.
    """
    if info is None:
        return "-"
    bl, net = info.bl_version, info.net_version
    if not bl and not net:
        return "-"

    bl_base, bl_dirty = _split_dirty(bl)
    net_base, net_dirty = _split_dirty(net)
    if bl_base != net_base:
        return f"[yellow]{bl or '?'} / {net or '?'}"

    version = bl_base or net_base
    if bl_dirty and net_dirty:
        return f"{version} [yellow](dirty)"
    if bl_dirty:
        return f"{version} [yellow](bl dirty)"
    if net_dirty:
        return f"{version} [yellow](net dirty)"
    return version


def format_lh2_calibration(info: DeviceInfo | None) -> str:
    """The calibration line, including the case where nothing is known.

    A device that never answered and a device reporting zero homographies are
    different facts, and an operator acts on each differently: one is a bot to
    re-provision, the other is a fetch that has not landed yet. Dropping the
    line for the first case made them look identical.
    """
    if info is None:
        return "unknown (no device info)"
    return info.lh2_summary


def format_lh2_cell(info: DeviceInfo | None) -> str:
    """The compact form of the calibration state, for the fleet table.

    Same vocabulary as the image cell: "-" for a bot that has not answered,
    "none" for one that answered and carries no calibration. The column only
    appears when the fleet disagrees, where the question is which bots differ
    rather than how each was provisioned, so the count alone carries it and
    the full summary stays in the header line and the per-device panel. The
    summary spelled out per row wraps to four lines in a table this wide.
    """
    if info is None:
        return "-"
    if not info.lh2_homography_count:
        return "none"
    return str(info.lh2_homography_count)


def format_position(status: NodeStatus) -> str:
    """Where the bot is, or which of the two reasons it is nowhere.

    `current_position` in shared memory is zero-initialised and only written
    once a fix succeeds, and the calibrated arena never contains the origin,
    so (0, 0) means no fix rather than a coordinate. The two reasons call for
    opposite actions: `uncalibrated` (device info reports no homographies)
    means re-provision the bot; `no fix` means check lighthouse coverage or
    placement.
    """
    if status.pos_x == 0 and status.pos_y == 0:
        if status.info is not None and not status.info.lh2_homography_count:
            return "uncalibrated"
        return "no fix"
    return f"{status.pos_x}, {status.pos_y}"


FW_CELL = 6  # index of the sandbox-fw cell in a status row
LH2_CELL = 7  # index of the LH2-calibration cell in a status row


def _visible_cells(row, show_fw: bool, show_lh2: bool) -> tuple:
    """Drop the cells whose column collapsed into the header this run."""
    hidden = set()
    if not show_fw:
        hidden.add(FW_CELL)
    if not show_lh2:
        hidden.add(LH2_CELL)
    return tuple(cell for i, cell in enumerate(row) if i not in hidden)


def _status_table(rows, show_fw: bool = True, show_lh2: bool = True) -> Table:
    """One status table over `rows`, each a tuple of preformatted cells."""
    table = Table()
    table.add_column("Device Addr", style="magenta", no_wrap=True)
    table.add_column("Type", style="cyan", justify="center")
    table.add_column("Battery", style="cyan", justify="center")
    table.add_column("Position", style="cyan", justify="center")
    table.add_column(
        "Status",
        style="green",
        justify="center",
        width=max([len(m) for m in StatusType.__members__]),
    )
    table.add_column("Image", style="cyan", justify="center")
    if show_fw:
        table.add_column(
            "Sandbox fw (bl / net)", style="cyan", justify="center"
        )
    if show_lh2:
        table.add_column("LH2", style="cyan", justify="center")
    table.add_column("Last reset", style="cyan", justify="center")
    for row in rows:
        table.add_row(*_visible_cells(row, show_fw, show_lh2))
    return table


def _status_columns(
    rows, show_fw: bool = True, show_lh2: bool = True, console=None
):
    """Lay the rows out in newspaper columns when one table would not fit.

    A hundred-bot fleet is one row per bot and far taller than any terminal,
    while the table itself uses maybe half the width - so the run scrolls off
    the top with the right-hand side of the screen empty. Split the rows
    across side-by-side tables instead, as many as fit the width and only as
    many as the height actually needs.

    Below that threshold nothing changes: one table, exactly as before.
    """
    console = console or get_console()
    single = _status_table(rows, show_fw=show_fw, show_lh2=show_lh2)
    if not rows:
        return single

    table_width = console.measure(single).maximum
    gap = 2
    fit_across = (console.width + gap) // (table_width + gap)
    # Header, borders and the surrounding blank lines cost about this much.
    body_height = max(1, console.size.height - 8)
    needed = -(-len(rows) // body_height)  # ceil

    n = max(1, min(fit_across, needed, len(rows)))
    if n <= 1:
        return single

    per = -(-len(rows) // n)  # ceil, so the last column is the short one
    chunks = [rows[i : i + per] for i in range(0, len(rows), per)]
    return Columns(
        [
            _status_table(chunk, show_fw=show_fw, show_lh2=show_lh2)
            for chunk in chunks
        ],
        padding=(0, 1),
        expand=False,
    )


def generate_status(status_data, devices=[], status_message="found"):
    data = {
        addr: device_data
        for addr, device_data in status_data.items()
        if (devices and addr in devices) or (not devices)
    }
    if not data:
        return Group(Text(f"\nNo device {status_message}\n"))

    header = Text(
        f"\n{len(data)} device{'s' if len(data) > 1 else ''} {status_message}\n"
    )

    majority, odd_ones = image_mismatches(data)
    odd_addrs = {addr for addr, _ in odd_ones}
    rows = []
    for device_addr, device_data in sorted(data.items()):
        info = device_data.info
        # "-" means the bot has not answered yet, which is what an older
        # bootloader looks like. It is deliberately not the same as a blank
        # name on a bot that did answer - that falls back to the digest.
        image = info.image_label if info else "-"
        if device_addr in odd_addrs:
            image = f"[yellow]{image}"

        rows.append(
            (
                f"{device_addr}",
                f"{device_data.device.name}",
                f"[{battery_level_color(device_data)}]{device_data.battery / 1000:.2f}V "
                f"({battery_pct(device_data.device, device_data.battery)}%)",
                format_position(device_data),
                f"{'[bold cyan]' if device_data.status == StatusType.Running else '[bold green]'}{device_data.status.name}",
                image,
                format_sandbox_fw(info),
                format_lh2_cell(info),
                f"[{reset_cause_color(device_data)}]{format_reset_cause(device_data)}",
            )
        )

    # A fleet is normally flashed in one go, so the sandbox version is the same
    # string on every row - 34 columns spent to say one thing N times, and the
    # width that decides whether the table can be laid out side by side. State
    # it once above the table instead, and keep the column only when the fleet
    # actually disagrees, which is the case worth a column.
    fw_values = {row[FW_CELL] for row in rows}
    show_fw = len(fw_values) > 1
    if not show_fw:
        only = next(iter(fw_values))
        if only != "-":
            header = Text.assemble(
                header, Text.from_markup(f"Sandbox fw (bl / net): {only}\n")
            )

    # One arena, one calibration run, so calibration has the same distribution
    # as the sandbox version above and earns a column on the same terms.
    # Compared on the full summary rather than the count in the cell, so a
    # fleet that agrees on the count but not on the flags still gets a column.
    lh2_summaries = {
        device_data.info.lh2_summary if device_data.info else "-"
        for device_data in data.values()
    }
    show_lh2 = len(lh2_summaries) > 1
    if not show_lh2:
        only = next(iter(lh2_summaries))
        if only != "-":
            header = Text.assemble(
                header, Text.from_markup(f"LH2 calibration: {only}\n")
            )

    table = _status_columns(rows, show_fw=show_fw, show_lh2=show_lh2)
    if not odd_ones:
        return Group(header, table)

    # The point of putting a digest on the wire: the odd bot out surfaces
    # without an operator reading a hundred rows.
    plural = "s" if len(odd_ones) > 1 else ""
    lines = [
        Text(""),
        Text(
            f"! {len(odd_ones)} of {len(data)} device{plural} "
            f"differ{'' if len(odd_ones) > 1 else 's'} from the fleet majority:",
            style="yellow",
        ),
    ]
    for addr, info in odd_ones:
        label = f" ({info.image_name})" if info.image_name else ""
        lines.append(
            Text(
                f"    {addr}  image {info.image_digest[:16]}{label}, "
                f"majority is {majority[:16]}",
                style="yellow",
            )
        )
    return Group(header, table, *lines)


def generate_info(status_data, devices=[], show_raw=False):
    """Full per-device detail: every status field plus what the bot is running.

    The status table shows a friendly one-line reset cause; this decodes
    everything the bot reports, for post-mortem of a specific robot.
    `show_raw` appends the wire bytes of both packets, which are useful for
    protocol work and noise for everything else.
    """
    data = {
        addr: device_data
        for addr, device_data in status_data.items()
        if (devices and addr in devices) or (not devices)
    }
    if not data:
        return Group(Text("\nNo matching device\n"))
    has_raw = False

    panels = [Text("")]
    for device_addr, d in sorted(data.items()):
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("field", style="bold cyan", no_wrap=True)
        table.add_column("value")

        table.add_row("Type", d.device.name)
        table.add_row("Status", d.status.name)
        table.add_row(
            "Battery",
            f"[{battery_level_color(d)}]{d.battery / 1000:.2f}V "
            f"({battery_pct(d.device, d.battery)}%)",
        )
        table.add_row("Position", format_position(d))
        if d.last_updated_at:
            age = max(0.0, time.time() - d.last_updated_at)
            table.add_row("Last update", f"{age:.1f}s ago")

        if d.info is not None:
            info = d.info
            table.add_row("", "")
            table.add_row("Image", info.image_label)
            if info.image_version:
                table.add_row("  version", info.image_version)
            if info.has_image and info.image_digest:
                table.add_row("  digest", info.image_digest)
            if info.image_size:
                chunks = -(-info.image_size // CHUNK_SIZE)
                table.add_row(
                    "  size", f"{info.image_size} B ({chunks} chunks)"
                )
            table.add_row(
                "  state",
                f"{info.image_state_name} / {info.image_result_name}",
            )

            table.add_row("", "")
            table.add_row("Sandbox fw", f"bootloader  {info.bl_version}")
            table.add_row("", f"netcore     {info.net_version}")
            # Boot count only. Why it booted is answered twice below, in more
            # detail and from the authoritative register - a third rendering,
            # in the coarse Matter vocabulary, is noise here. That mapping
            # exists for a gateway-side bridge, not for this panel.
            table.add_row(
                "Uptime",
                f"{format_uptime(info.uptime_s)}   "
                f"(boot #{info.boot_count})",
            )

        # Outside the device-info block on purpose: a bot that has not answered
        # still gets a calibration line, saying so, rather than none at all.
        table.add_row("", "")
        table.add_row("LH2 calibration", format_lh2_calibration(d.info))

        table.add_row("", "")
        table.add_row(
            "Last reset",
            f"[{reset_cause_color(d)}]{format_reset_cause(d)}",
        )
        decoded = decode_reset_reason(d.reset_reason)
        table.add_row(
            "  reset_reason",
            # The bit-by-bit decode earns its place only when it says more than
            # the friendly cause above it - 0x1c spelling out
            # "ctrl-ap+soft-reset+lockup" is worth a line, "soft-reset" under
            # "soft-reset" is stutter.
            f"0x{d.reset_reason:08x}"
            + (f" ({decoded})" if decoded != format_reset_cause(d) else ""),
        )
        table.add_row(
            "  fault",
            f"{fault_name(d)}"
            + (" (non-secure)" if d.fault and d.from_ns else "")
            + (" (secure)" if d.fault and not d.from_ns else ""),
        )
        if d.fault:
            # Only a real fault sets these. A watchdog timeout raised none, so
            # both registers read zero - printing them invites the reader to
            # decode a status that was never populated.
            if d.fault in (
                FaultType.HardFault.value,
                FaultType.SecureFault.value,
            ):
                cfsr_bits = decode_cfsr(d.cfsr)
                sfsr_bits = decode_sfsr(d.sfsr)
                table.add_row(
                    "  cfsr",
                    f"0x{d.cfsr:08x}"
                    + (f" ({cfsr_bits})" if cfsr_bits else ""),
                )
                table.add_row(
                    "  sfsr",
                    f"0x{d.sfsr:08x}"
                    + (f" ({sfsr_bits})" if sfsr_bits else ""),
                )
            elf = "app image" if d.from_ns else "bootloader image"
            table.add_row("  pc", f"0x{d.pc:08x}  (resolve against {elf})")
            table.add_row("  lr", f"0x{d.lr:08x}")
            table.add_row("  sp", f"0x{d.sp:08x}")
            # The IPSR decode is the point of carrying psr: it says whether the
            # bot was in an interrupt handler, which a pc in a shared driver
            # function cannot tell you on its own.
            table.add_row("  psr", f"0x{d.psr:08x}  (in {decode_ipsr(d.psr)})")

        # Both raw packets together, because the pair is what makes the two
        # channels legible: the status frame arrives every second and its last
        # byte is the generation counter, while the device-info reply arrives
        # only when that counter moves and ends with the LH2 fields. Same tail
        # position, unrelated meanings, easy to misread with only one in view.
        # Off by default - 156 bytes of hex is most of the panel, and nobody
        # reading battery and uptime wants it.
        if show_raw:
            if d.raw:
                table.add_row("", "")
                table.add_row("Raw status pkt", _hex_dump(d.raw))
            if d.info is not None and d.info.raw:
                table.add_row("", "")
                table.add_row("Raw device info", _hex_dump(d.info.raw))
        elif d.raw or (d.info is not None and d.info.raw):
            has_raw = True
        panels.append(
            Panel(
                table,
                title=f"[bold magenta]{device_addr}[/]",
                title_align="left",
                border_style="cyan",
                padding=(0, 1),
                expand=False,
            )
        )
        panels.append(Text(""))
    if has_raw:
        # One line for the whole run, not per panel: the bytes are two
        # keystrokes away instead of hidden, and cost nothing when unwanted.
        panels.append(
            Text("  wire bytes available: re-run with --raw", style="dim")
        )
        panels.append(Text(""))
    return Group(*panels)


def print_transfer_status(
    status: dict[str, TransferDataStatus], start_data: int
) -> None:
    """Print the transfer status."""
    print()
    print("[bold]Transfer status:[/]")
    transfer_status_table = Table()
    transfer_status_table.add_column(
        "Device Addr", style="magenta", no_wrap=True
    )
    transfer_status_table.add_column(
        "Chunks acked", style="green", justify="center"
    )

    with Live(transfer_status_table, refresh_per_second=4) as live:
        live.update(transfer_status_table)
        for device_addr, status in sorted(status.items()):
            chunks_col_color = "[green]" if status.success else "[bold red]"
            transfer_status_table.add_row(
                f"{device_addr}",
                f"{chunks_col_color}{len([chunk for chunk in status.chunks if bool(chunk.acked)])}/{start_data.chunks}",
            )


def wait_for_done(timeout):
    """Wait for the condition to be met."""
    while timeout > 0:
        timeout -= 0.01
        time.sleep(0.01)
    return False


@dataclass
class ControllerSettings:
    """Class that holds controller settings."""

    serial_port: str = SERIAL_PORT_DEFAULT
    serial_baudrate: int = 1000000
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_use_tls: bool = False
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    network_id: int = 1
    adapter: str = "serial"  # or "mqtt", "marilib-edge", "marilib-cloud"
    devices: list[str] = dataclasses.field(default_factory=lambda: [])
    # The rectangles of the frame the dashboard draws and clips to, each
    # [x, y, w, h] in mm. A view of the frame, never a calibration.
    bounds: list[list[int]] = dataclasses.field(
        default_factory=lambda: [[0, 0, 2000, 2000]]
    )
    # The placements' points, in frame mm, that the dashboard draws crosses at.
    reference_points: list[list[float]] = dataclasses.field(
        default_factory=lambda: []
    )
    # OTA_START retry budget (the block transfer does its own repair rounds).
    ota_max_retries: int = OTA_MAX_RETRIES_DEFAULT
    ota_timeout: float = OTA_ACK_TIMEOUT_DEFAULT
    # Share of the gateway's downlink the OTA transfer may drive, and the
    # per-bot chunk-write ceiling. Together they set the chunk inject rate.
    ota_utilization: float = OTA_DOWNLINK_UTILIZATION
    ota_device_chunk_rate: float = DEVICE_CHUNK_RATE_HZ
    # Report-collection window in seconds; 0 derives it from the link geometry.
    # Too short and a report arriving after the broker round trip reads as
    # missing, costing a spurious repair round.
    ota_report_timeout: float = 0
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
        # OTA protocol version reported per bot in its OTA_START_ACK (1 = legacy
        # per-chunk, 2 = block/bitmap). Drives the transfer-path choice.
        self._ota_versions: dict[str, int] = {}
        # Active block transfer, so RX-thread report/finalize frames can be fed
        # into it. None outside a block-OTA transfer.
        self._block_transfer: BlockTransfer | None = None
        # Device-info cache, keyed by address.
        self._device_info: dict[str, DeviceInfo] = {}
        # Per-device retry state: how long to wait before asking again, and
        # when that wait expires. Both reset the moment a device answers
        # usefully or its generation moves.
        self._info_backoff: dict[str, float] = {}
        self._info_next_try: dict[str, float] = {}
        self._info_gen_seen: dict[str, int] = {}
        self._info_last_broadcast: float = 0.0
        # Addresses an explicit fetch is waiting on a fresh reply for,
        # regardless of the generation counter. Cleared as replies land.
        self._info_forced: set[str] = set()
        self._known_devices: dict[str, StatusType] = {}
        self._log_event_listeners: list = []
        self._log_listeners_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True
        )
        if self.settings.adapter == "cloud":
            self._interface = MarilibCloudAdapter(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                self.settings.mqtt_use_tls,
                self.settings.network_id,
                verbose=self.settings.verbose,
                busy_wait_timeout=self.settings.adapter_wait_timeout,
                username=self.settings.mqtt_username,
                password=self.settings.mqtt_password,
            )
        else:
            self._interface = MarilibEdgeAdapter(
                self.settings.serial_port,
                self.settings.serial_baudrate,
                verbose=self.settings.verbose,
                busy_wait_timeout=self.settings.adapter_wait_timeout,
            )
        self._interface.init(self.on_frame_received)
        self._cleanup_thread.start()

    @property
    def known_devices(self) -> dict[str, StatusType]:
        """Return the known devices."""
        if not self._known_devices:
            wait_for_done(COMMAND_TIMEOUT)
            self._known_devices = self.status_data
        return self._known_devices

    @property
    def running_devices(self) -> list[str]:
        """Return the running devices."""
        return [
            addr
            for addr, node in self.known_devices.items()
            if (
                (
                    node.status == StatusType.Running
                    or node.status == StatusType.Programming
                )
                and (
                    not self.settings.devices or addr in self.settings.devices
                )
            )
        ]

    @property
    def resetting_devices(self) -> list[str]:
        """Return the resetting devices."""
        return [
            device_addr
            for device_addr, node in self.known_devices.items()
            if (
                node.status == StatusType.Resetting
                and (
                    not self.settings.devices
                    or device_addr in self.settings.devices
                )
            )
        ]

    @property
    def ready_devices(self) -> list[str]:
        """Return the ready devices."""
        return [
            device_addr
            for device_addr, node in self.known_devices.items()
            if (
                node.status == StatusType.Bootloader
                and (
                    not self.settings.devices
                    or device_addr in self.settings.devices
                )
            )
        ]

    @property
    def interface(self) -> GatewayAdapterBase:
        """Return the interface."""
        return self._interface

    def _cleanup_loop(self):
        while not self._stop_event.is_set():
            self.cleanup_inactive(INACTIVE_TIMEOUT)
            self._refresh_stale_device_info()
            time.sleep(1)

    def cleanup_inactive(self, timeout):
        now = time.time()
        # Snapshot with list(): the RX thread inserts into status_data as
        # frames arrive, and iterating it live raises RuntimeError.
        inactive = [
            addr
            for addr, status in list(self.status_data.items())
            if now - status.last_updated_at > timeout
        ]
        for addr in inactive:
            self.status_data.pop(addr, None)
            self._device_info.pop(addr, None)
            self._info_backoff.pop(addr, None)
            self._info_next_try.pop(addr, None)
            self._info_gen_seen.pop(addr, None)
            self._info_forced.discard(addr)

    def stale_device_info(self) -> list[str]:
        """Devices whose cached device info no longer matches their status.

        A bot is stale when it has never answered, or when the generation
        counter in its status frame has moved past the one its last reply
        carried. Bots that have ignored the request often enough to look like
        older firmware are excluded.
        """
        now = time.time()
        stale = []
        for addr, status in list(self.status_data.items()):
            # Zero means the device never sent a counter at all, which is what
            # firmware predating this message looks like once the short status
            # frame is zero-filled. That is a property of the device rather
            # than a guess from a timeout, so it is never asked - not even when
            # forced, since it cannot answer.
            if status.info_gen == 0:
                continue
            # An explicit ask counts as stale whatever the counter says: some
            # of this block is not inventory. `uptime_s` changes every second,
            # so "the generation has not moved" does not mean "the values are
            # still true", and `info` exists to answer as of now.
            forced = addr in self._info_forced
            cached = self._device_info.get(addr)
            if (
                not forced
                and cached is not None
                and cached.info_gen == status.info_gen
            ):
                continue
            if not forced and now < self._info_next_try.get(addr, 0.0):
                continue
            stale.append(addr)
        return stale

    def _refresh_stale_device_info(self):
        """Ask the fleet for device info, but only when something changed.

        This is the whole point of the generation counter: in steady state
        nothing is stale and not a single packet goes out. A flash campaign or
        a reboot moves the counter and costs exactly one broadcast, which every
        stale bot answers in its own uplink cell.
        """
        stale = self.stale_device_info()
        if not stale:
            return
        now = time.time()
        if now - self._info_last_broadcast < DEVICE_INFO_REFRESH_INTERVAL:
            return
        self._info_last_broadcast = now
        for addr in stale:
            # Double the wait each time it goes unanswered, up to the ceiling.
            backoff = min(
                self._info_backoff.get(addr, 0.0) * 2
                or DEVICE_INFO_REFRESH_INTERVAL,
                DEVICE_INFO_BACKOFF_MAX,
            )
            self._info_backoff[addr] = backoff
            self._info_next_try[addr] = now + backoff
        try:
            self.request_device_info()
        except Exception:
            # The refresh runs on the cleanup thread; a transport hiccup here
            # must not take that thread down with it.
            self.logger.debug("device info refresh failed", exc_info=True)

    def request_device_info(self, devices=None):
        """Ask devices to emit their device-info block once.

        Broadcast by default: bots reply in their own uplink cells, so one
        request reaches the whole fleet for the cost of a single downlink
        packet.
        """
        payload = PayloadRequestMessage(
            msg_id=PayloadType.SWARMIT_DEVICE_INFO_RESP
        )
        if not devices:
            self.send_payload(BROADCAST_ADDRESS, payload)
            return
        for addr in devices:
            self.send_payload(int(addr, 16), payload)

    def fetch_device_info(
        self, devices=None, timeout=DEVICE_INFO_TIMEOUT
    ) -> dict[str, DeviceInfo]:
        """Request device info and wait for the replies to land.

        Used by the `info` command, which asks explicitly rather than waiting
        for the background refresh. Returns whatever arrived; a device that
        never answers is simply absent.
        """
        # Upper-cased because that is what addr_to_hex produces for the
        # status_data keys these are intersected against. A lower-case -d
        # argument would otherwise intersect to nothing and the loop would
        # exit on the first pass without ever sending a request.
        wanted = (
            {addr.upper() for addr in devices}
            if devices
            else set(self.status_data)
        )
        # An explicit ask cancels any backoff, so an operator running `info`
        # does not wait out a retry interval the sweep happened to be in.
        for addr in wanted:
            self._info_backoff.pop(addr, None)
            self._info_next_try.pop(addr, None)
        # Demand a genuinely fresh reply rather than accepting the cached
        # block. The cache stays in place meanwhile, so a device that never
        # answers still renders what was last known instead of nothing.
        self._info_forced |= wanted
        deadline = time.time() + timeout
        next_send = 0.0
        while time.time() < deadline:
            # Waiting on "cached at all" would return immediately with the
            # entry from before the change; wait for the generation counters
            # to line up instead.
            if not wanted & set(self.stale_device_info()):
                break
            # Re-ask rather than send once and hope. A bot running a chatty
            # user image is contending for the single uplink cell it owns per
            # slotframe, and a 156-byte reply loses that race often enough that
            # one request inside the window frequently returns nothing. Sending
            # stops the moment every wanted device has answered.
            now = time.time()
            if now >= next_send:
                self.request_device_info(devices)
                next_send = now + DEVICE_INFO_RESEND_INTERVAL
            time.sleep(0.01)
        # Drop the demand whether or not it was met, so a device that stayed
        # silent does not keep the background sweep broadcasting for it.
        self._info_forced -= wanted
        return {
            addr: info
            for addr, info in self._device_info.items()
            if addr in wanted
        }

    def terminate(self):
        """Terminate the controller."""
        self._stop_event.set()
        self._cleanup_thread.join()
        self.interface.close()

    def add_log_event_listener(self, callback) -> None:
        """Register `callback(event_dict)` for each SWARMIT_EVENT_LOG payload.

        The callback is invoked from the marilib RX thread, so it must
        not block. Listeners typically push the event into an
        asyncio.Queue (webserver) or queue.Queue (in-process client).
        """
        with self._log_listeners_lock:
            self._log_event_listeners.append(callback)

    def remove_log_event_listener(self, callback) -> None:
        with self._log_listeners_lock:
            try:
                self._log_event_listeners.remove(callback)
            except ValueError:
                pass

    def send_payload(self, destination: int, payload: Payload):
        """Send a frame to the devices."""
        self.interface.send_payload(destination, payload)

    def on_frame_received(self, header, packet: Packet):
        """Handle the received frame."""
        device_addr = f"{header.source:08X}"
        if packet.payload_type == PayloadType.SWARMIT_STATUS:
            now = time.time()
            status = NodeStatus(
                device=DeviceType(packet.payload.device),
                status=StatusType(packet.payload.status),
                battery=packet.payload.battery,
                pos_x=packet.payload.pos_x,
                pos_y=packet.payload.pos_y,
                reset_reason=packet.payload.reset_reason,
                fault=packet.payload.fault,
                from_ns=packet.payload.from_ns,
                cfsr=packet.payload.cfsr,
                sfsr=packet.payload.sfsr,
                pc=packet.payload.pc,
                lr=packet.payload.lr,
                sp=packet.payload.sp,
                psr=packet.payload.psr,
                raw=packet.to_bytes().hex(),
                last_updated_at=now,
                info_gen=packet.payload.info_gen,
                # Carried over rather than refetched: the block only changes
                # when the generation counter says it did.
                info=self._device_info.get(device_addr),
            )
            if self._info_gen_seen.get(device_addr) != status.info_gen:
                self._info_gen_seen[device_addr] = status.info_gen
                # Something changed on this bot, so it is worth asking again
                # immediately even if it had been backing off.
                self._info_backoff.pop(device_addr, None)
                self._info_next_try.pop(device_addr, None)
            self.status_data.update({device_addr: status})
        elif packet.payload_type == PayloadType.SWARMIT_DEVICE_INFO_RESP:
            info = DeviceInfo.from_payload(
                packet.payload, raw=packet.to_bytes().hex()
            )
            if (
                info.info_version == 0
                or info.info_version > DEVICE_INFO_VERSION
            ):
                # A truncated body zero-fills to version 0; a schema newer than
                # this host parses as something higher. Neither is usable, and
                # neither must clear the attempt counter, or a device that
                # always answers unusably is re-broadcast for the life of the
                # session. This is what `info_version` is on the wire for.
                self.logger.debug(
                    "unusable device info",
                    device_addr=device_addr,
                    info_version=info.info_version,
                )
                return
            self._device_info[device_addr] = info
            self._info_forced.discard(device_addr)
            # `.get()` rather than `in` then `[]`: this runs on the marilib RX
            # thread while the cleanup thread deletes inactive entries, and the
            # two-step form raises KeyError when a device times out between the
            # check and the write.
            cached_status = self.status_data.get(device_addr)
            if cached_status is not None:
                cached_status.info = info
                # Clear the cap only when the reply actually resolves the
                # staleness. Clearing on any reply means a device whose
                # generation never lines up resets the counter every time and
                # is asked again forever, which is the opposite of a cap.
                if info.info_gen == cached_status.info_gen:
                    self._info_backoff.pop(device_addr, None)
                    self._info_next_try.pop(device_addr, None)
        elif packet.payload_type == PayloadType.SWARMIT_OTA_START_ACK:
            # A bootloader speaking the block protocol appends its version; a
            # legacy one sends the empty ack, which parses as version 1.
            self._ota_versions[device_addr] = getattr(
                packet.payload, "version", OTA_PROTOCOL_VERSION_LEGACY
            )
            if device_addr not in self.start_ota_data.addrs:
                self.start_ota_data.addrs.append(device_addr)
        elif packet.payload_type == PayloadType.SWARMIT_OTA_BLOCK_REPORT_RESP:
            if self._block_transfer is not None:
                self._block_transfer.on_report(
                    device_addr,
                    packet.payload.block_index,
                    packet.payload.received_mask,
                )
        elif packet.payload_type == PayloadType.SWARMIT_OTA_FINALIZE_RESP:
            if self._block_transfer is not None:
                self._block_transfer.on_finalize_resp(
                    device_addr, bool(packet.payload.ok)
                )
        elif packet.payload_type == PayloadType.SWARMIT_OTA_CHUNK_ACK:
            # Retired with the per-chunk path. Only a bootloader older than
            # this controller supports still sends these; parse and drop.
            self.logger.debug(
                "ignoring retired per-chunk ack",
                device_addr=device_addr,
                chunk_index=packet.payload.index,
            )
        elif packet.payload_type == PayloadType.SWARMIT_EVENT_LOG:
            if (
                self.settings.devices
                and device_addr not in self.settings.devices
            ):
                return
            logger = self.logger.bind(
                device_addr=device_addr,
                notification=PayloadType(packet.payload_type).name,
                timestamp=packet.payload.timestamp,
                data_size=packet.payload.count,
                data=packet.payload.data,
            )
            logger.info("LOG event")
            # Fan out to registered listeners (used by /events SSE in
            # daemon mode and LocalSwarmitClient.watch_log_events). Hex
            # the payload so it survives JSON round-tripping.
            event = {
                "addr": device_addr,
                "timestamp": packet.payload.timestamp,
                "data_size": packet.payload.count,
                "data_hex": bytes(packet.payload.data).hex(),
            }
            with self._log_listeners_lock:
                listeners = list(self._log_event_listeners)
            for cb in listeners:
                try:
                    cb(event)
                except Exception:
                    # never let a misbehaving listener kill the RX thread
                    pass

    def _live_status(self, timeout, devices=[], message="found", watch=False):
        """Request the live status of the testbed."""
        with Live(
            generate_status(self.status_data, devices, status_message=message),
            refresh_per_second=4,
        ) as live:
            while watch is True or timeout > 0:
                live.update(
                    generate_status(
                        self.status_data, devices, status_message=message
                    )
                )
                timeout -= 0.01
                time.sleep(0.01)

    def status(self, timeout=STATUS_TIMEOUT, watch=False):
        """Request the status of the testbed."""
        self._live_status(timeout, devices=self.settings.devices, watch=watch)

    def _send_start(self, device_addr: str):
        payload = PayloadStart()
        self.send_payload(int(device_addr, 16), payload)

    def start(self, devices=None):
        """Start the application.

        Returns once every target reports Running, or after
        COMMAND_MAX_ATTEMPTS tries. Rendering the result is the caller's job.
        """
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
                self._send_start(addr_to_hex(BROADCAST_ADDRESS))
            else:
                for device_addr in devices_to_start:
                    self._send_start(device_addr)
            attempts += 1
            time.sleep(COMMAND_ATTEMPT_DELAY)

    def stop(self, devices=None):
        """Stop the application.

        The application keeps running for about a second after the request:
        the device stops by arming WDT1, not by resetting the core.
        """
        if devices is None:
            devices = self.settings.devices or []
        stoppable_devices = self.running_devices + self.resetting_devices
        devices_to_stop = (
            stoppable_devices
            if not devices
            else [d for d in devices if d in stoppable_devices]
        )

        attempts = 0
        while attempts < COMMAND_MAX_ATTEMPTS and not all(
            self.status_data[addr].status
            in [StatusType.Stopping, StatusType.Bootloader]
            for addr in devices_to_stop
        ):
            if not devices:
                self.send_payload(BROADCAST_ADDRESS, PayloadStop())
            else:
                for device_addr in devices_to_stop:
                    self.send_payload(int(device_addr, 16), PayloadStop())
            attempts += 1
            time.sleep(COMMAND_ATTEMPT_DELAY)

    def _send_reset(self, device_addr: int, location: ResetLocation):
        payload = PayloadReset(
            pos_x=location.pos_x,
            pos_y=location.pos_y,
        )
        self.send_payload(device_addr, payload)

    def reset(self, locations: dict[str, ResetLocation]):
        """Reset the application."""
        ready_devices = self.ready_devices
        for device_addr in self.settings.devices:
            if device_addr not in ready_devices:
                continue
            print(
                f"Resetting device {device_addr} with location {locations[device_addr]}"
            )
            self._send_reset(int(device_addr, 16), locations[device_addr])

    def monitor(
        self, timeout: float = MONITOR_TIMEOUT, run_forever: bool = True
    ):
        """Monitor the testbed."""
        self.logger.info("Monitoring testbed")
        while timeout > 0 or run_forever:
            time.sleep(0.01)
            timeout -= 0.01

    def _send_message(self, device_addr: int, message: str):
        payload = PayloadMessage(
            count=len(message),
            message=message.encode(),
        )
        self.send_payload(device_addr, payload)

    def send_message(self, message):
        """Send a message to the devices."""
        running_devices = self.running_devices
        if not self.settings.devices:
            self._send_message(BROADCAST_ADDRESS, message)
        else:
            for addr in self.settings.devices:
                if addr not in running_devices:
                    continue
                self._send_message(int(addr, 16), message)

    def send_lh2_calibration(self, calibration_file: bytes):
        matrix_size = 3 * 3 * 4  # 3x3, each element is 4 bytes
        if not calibration_file:
            raise ValueError("Calibration file is empty")

        # Supported format: 1-byte count + N * 36 bytes
        if (
            len(calibration_file) < 1
            or (len(calibration_file) - 1) % matrix_size != 0
        ):
            raise ValueError(
                f"Invalid calibration file size: expected 1+N*{matrix_size} bytes (count byte + matrices)"
            )

        homography_count = calibration_file[0]
        matrices_bytes = calibration_file[1:]
        expected_count = len(matrices_bytes) // matrix_size
        if homography_count != expected_count:
            raise ValueError(
                "Invalid calibration file: count byte does not match matrix payload length"
            )
        if homography_count == 0:
            raise ValueError(
                "Invalid calibration file: homography count cannot be zero"
            )

        if homography_count > 16:
            raise ValueError(
                "Invalid calibration file: homography count exceeds LH2 limit (16)"
            )

        ready_devices = self.ready_devices
        if not ready_devices:
            print(
                f"Sending {homography_count} calibration matrix/matrices to {BROADCAST_ADDRESS}..."
            )
        else:
            print(
                f"Sending {homography_count} calibration matrix/matrices to {len(ready_devices)} devices: {str(ready_devices)}..."
            )

        for homography_index in range(homography_count):
            print(f"Sending calibration matrix {homography_index}...")
            start = homography_index * matrix_size
            end = start + matrix_size
            payload = PayloadCalibrationData(
                homography_count=homography_count,
                homography_index=homography_index,
                homography=matrices_bytes[start:end],
            )
            if self.settings.verbose:
                print(payload)
                print(Packet.from_payload(payload).to_bytes())
            for _ in range(COMMAND_MAX_ATTEMPTS):
                # simple strategy to bypass non-reliable link layer, just send the payload multiple times
                if not ready_devices:
                    self.send_payload(BROADCAST_ADDRESS, payload)
                else:
                    for device_addr in ready_devices:
                        self.send_payload(int(device_addr, 16), payload)
                time.sleep(
                    0.3
                )  # give the device some time to process the payload

    def request_lh2_capture(self, device_addr: str):
        """Trigger a single raw LH2 capture on one device.

        The bot replies (only while READY) with a SWARMIT_EVENT_LOG whose
        payload starts with LH2_CALIB_TAG. Delivery is best-effort: callers
        await that log event and re-issue on timeout rather than relying on
        this single send.
        """
        self.send_payload(int(device_addr, 16), PayloadLH2Capture())

    def _send_start_ota(
        self,
        device_addr: str,
        devices_to_flash: set[str],
        firmware: bytes,
        image_name: str = "",
        image_version: str = "",
    ):
        def is_start_ota_acknowledged():
            if int(device_addr, 16) == BROADCAST_ADDRESS:
                return sorted(self.start_ota_data.addrs) == sorted(
                    devices_to_flash
                )
            else:
                return device_addr in self.start_ota_data.addrs

        payload = PayloadOTAStart(
            fw_length=len(firmware),
            fw_chunk_count=len(self.chunks),
            image_name=image_name,
            image_version=image_version,
        )
        send_time = time.time()
        send = True
        while (
            not is_start_ota_acknowledged()
            and self.start_ota_data.retries <= self.settings.ota_max_retries
        ):
            if send is True:
                self.send_payload(int(device_addr, 16), payload)
                send_time = time.time()
                self.start_ota_data.retries += 1
            time.sleep(0.001)
            send = time.time() - send_time > self.settings.ota_timeout

    def start_ota(
        self,
        firmware,
        devices=None,
        image_name: str = "",
        image_version: str = "",
    ) -> dict:
        """Start the OTA process.

        `image_name` and `image_version` are display-only labels the device
        stores alongside the image and reports back. They are never the basis
        of a decision - the digest is the identity - so leaving them empty
        costs only readability.
        """
        if devices is None:
            devices = self.settings.devices or []
        # Pad the image to a 4-byte boundary: the device writes flash a 32-bit
        # word at a time, so a final chunk whose length is not a multiple of 4
        # would drop its tail bytes and fail the whole-image FINALIZE check.
        # 0xFF is the erased-flash value, so the padding is a no-op on device.
        firmware = bytes(firmware)
        if len(firmware) % 4:
            firmware = firmware + b"\xff" * (4 - len(firmware) % 4)
        self.start_ota_data = StartOtaData()
        self._ota_versions = {}
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
                    sha=chunk_sha.finalize()[
                        :8
                    ],  # the first 8 bytes should be enough
                    data=data,
                )
            )
        self.start_ota_data.fw_hash = digest.finalize()
        self.start_ota_data.chunks = len(self.chunks)
        devices_to_flash = self.ready_devices
        if not devices:
            print("Broadcast start ota notification...")
            self._send_start_ota(
                addr_to_hex(BROADCAST_ADDRESS),
                devices_to_flash,
                firmware,
                image_name,
                image_version,
            )
        else:
            for addr in devices:
                print(f"Sending start ota notification to {addr}...")
                self._send_start_ota(
                    addr, devices, firmware, image_name, image_version
                )
                time.sleep(0.2)
        return {
            "ota": self.start_ota_data,
            "acked": sorted(self.start_ota_data.addrs),
            "missed": sorted(
                set(devices).difference(set(self.start_ota_data.addrs))
            ),
        }

    @property
    def ota_block_size(self) -> int:
        """Chunks per block used by the OTA transfer."""
        return BLOCK_SIZE_DEFAULT

    def stale_bootloaders(self, devices) -> list[str]:
        """Devices whose OTA_START_ACK did not announce the block protocol.

        Their bootloader predates the block/bitmap path and only understands
        the retired per-chunk protocol. They cannot be flashed over the air by
        this controller; they need a re-provision over J-Link.
        """
        return sorted(
            addr
            for addr in devices
            if self._ota_versions.get(addr, OTA_PROTOCOL_VERSION_LEGACY)
            < OTA_PROTOCOL_VERSION_BLOCK
        )

    def transfer(
        self,
        firmware,
        devices,
        show_progress: bool = True,
    ) -> dict[str, TransferDataStatus]:
        """Transfer the firmware to the devices with the block/bitmap protocol.

        `show_progress` controls the built-in tqdm bar. Clients that render
        their own progress (e.g. the daemon's /flash/stream or
        LocalSwarmitClient.flash) pass False to avoid duplicate output.

        Bots on a pre-block bootloader are skipped rather than failing the
        run: one un-reprovisioned bot in a fleet of a hundred should not cost
        the other ninety-nine their flash. ``StaleBootloaderError`` is still
        raised when *every* target is stale, since then there is nothing to
        transfer and the caller asked for something impossible.
        """
        stale = self.stale_bootloaders(devices)
        if stale:
            remaining = [d for d in devices if d not in set(stale)]
            if not remaining:
                self.logger.error(
                    "ota aborted: every target has a stale bootloader",
                    devices=stale,
                    required_version=OTA_PROTOCOL_VERSION_BLOCK,
                )
                raise StaleBootloaderError(stale)
            self.logger.warning(
                "ota skipping stale bootloaders",
                devices=stale,
                required_version=OTA_PROTOCOL_VERSION_BLOCK,
            )
            devices = remaining
        data_size = len(firmware)
        use_progress_bar = show_progress and not self.settings.verbose
        progress = None
        if use_progress_bar:
            progress = tqdm(
                range(0, data_size),
                unit="B",
                unit_scale=False,
                colour="green",
                ncols=100,
            )
            progress.set_description(
                f"Loading firmware ({int(data_size / 1024)}kB, block OTA)"
            )

        self.transfer_data = {}
        for _addr in devices:
            self.transfer_data[_addr] = TransferDataStatus()
            self.transfer_data[_addr].chunks = [
                Chunk(index=f"{i:03d}", size=f"{self.chunks[i].size:03d}B")
                for i in range(len(self.chunks))
            ]

        def on_progress(addr: str, chunk_index: int) -> None:
            td = self.transfer_data.get(addr)
            if td is None or chunk_index >= len(td.chunks):
                return
            chunk = td.chunks[chunk_index]
            if not chunk.acked:
                chunk.acked = 1
                if progress is not None:
                    progress.update(self.chunks[chunk_index].size)

        broadcast = not self.settings.devices
        drop_chunks = _test_drop_chunks()
        if drop_chunks:
            self.logger.warning(
                "ota test: dropping chunks", chunks=sorted(drop_chunks)
            )
        # Pacing comes from the link the gateway reports; the adapter owns that
        # derivation because it owns everything radio-shaped.
        geometry = self.interface.link_geometry()
        if geometry is None:
            self.logger.warning(
                "ota pacing: gateway has not reported a schedule, "
                "using the fallback",
                schedule=LinkGeometry.fallback().schedule_name,
            )
        settings = derive_block_settings(
            geometry,
            len(devices),
            self.settings.ota_utilization,
            self.settings.ota_device_chunk_rate,
        )
        if self.settings.ota_report_timeout:
            settings.report_timeout = self.settings.ota_report_timeout
        transfer = BlockTransfer(
            chunks=self.chunks,
            devices=list(devices),
            send_payload=self.send_payload,
            image_sha=self.start_ota_data.fw_hash,
            settings=settings,
            broadcast=broadcast,
            on_progress=on_progress,
            logger=self.logger,
            drop_chunks=drop_chunks,
        )
        self.logger.info(
            "ota transfer start",
            image_bytes=data_size,
            total_chunks=len(self.chunks),
            schedule=(geometry or LinkGeometry.fallback()).schedule_name,
            block_size=settings.block_size,
            inter_chunk_ms=round(settings.inter_chunk_delay * 1000, 1),
            report_timeout_ms=round(settings.report_timeout * 1000, 1),
            devices=len(devices),
        )
        self._block_transfer = transfer
        start_ts = time.time()
        try:
            results = transfer.run()
        finally:
            self._block_transfer = None
        elapsed = time.time() - start_ts
        if progress is not None:
            progress.close()

        for addr, result in results.items():
            td = self.transfer_data.get(addr)
            if td is not None:
                td.success = result.success
        delivered = sum(r.confirmed_chunks for r in results.values())
        waste = transfer.chunk_sends / delivered if delivered else 0
        rate = delivered / elapsed if elapsed else 0
        failed = {a: r for a, r in results.items() if not r.success}
        self.logger.info(
            "ota transfer complete",
            elapsed_s=round(elapsed, 2),
            chunk_sends=transfer.chunk_sends,
            delivered=delivered,
            waste_ratio=round(waste, 2),
            chunk_per_s=round(rate, 2),
            ok=not failed,
            failed_devices=len(failed),
        )
        # Genuine failures (finalize SHA did not match, or no finalize response)
        # are surfaced at WARNING so they reach the console too, with the missing
        # chunk list for diagnosis.
        for addr, result in failed.items():
            missing = transfer.missing_chunks(addr)
            self.logger.warning(
                "ota device failed",
                addr=addr,
                confirmed=result.confirmed_chunks,
                total=result.total_chunks,
                finalized=result.finalized,
                straggler=result.straggler,
                missing_count=len(missing),
                missing_chunks=missing[:64],
            )
        # Image is good (finalize passed) but the delivery bitmap under-counted -
        # a sign the report path churned under load. Not a failure, but worth a
        # breadcrumb for tuning.
        for addr, result in results.items():
            if (
                result.success
                and result.confirmed_chunks < result.total_chunks
            ):
                self.logger.info(
                    "ota bitmap under-tracked",
                    addr=addr,
                    confirmed=result.confirmed_chunks,
                    total=result.total_chunks,
                )
        return self.transfer_data
