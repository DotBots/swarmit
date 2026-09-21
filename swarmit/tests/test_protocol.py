import pytest

from swarmit.testbed.controller import DeviceInfo
from swarmit.testbed.protocol import (
    CRASH_REPORT_SIZE,
    IMAGE_DIGEST_LEN,
    INFO_GEN_SIZE,
    INFO_STRING_LEN,
    LH2_FLAG_FLOAT32,
    STATUS_BASE_SIZE,
    FaultType,
    PayloadCalibrationData,
    PayloadDeviceInfo,
    PayloadOTAStart,
    PayloadRequestMessage,
    PayloadStatus,
    PayloadType,
    boot_reason,
    decode_cfsr,
    decode_ipsr,
    decode_reset_reason,
    decode_sfsr,
    decode_string_field,
    encode_string_field,
)


def test_payload_status_round_trip():
    payload = PayloadStatus(
        device=1,
        status=2,
        battery=2800,
        pos_x=100,
        pos_y=200,
        reset_reason=0x2,  # watchdog0
        fault=2,  # secure fault
        from_ns=1,
        cfsr=0x100,
        sfsr=0x8,
        pc=0x0001_2345,
        lr=0x0001_2340,
        info_gen=7,
    )
    raw = payload.to_bytes()
    assert len(raw) == STATUS_BASE_SIZE + CRASH_REPORT_SIZE + INFO_GEN_SIZE

    parsed = PayloadStatus().from_bytes(bytes(raw))
    assert parsed.info_gen == 7
    assert parsed.device == 1
    assert parsed.status == 2
    assert parsed.battery == 2800
    assert parsed.pos_x == 100
    assert parsed.pos_y == 200
    assert parsed.reset_reason == 0x2
    assert parsed.fault == 2
    assert parsed.from_ns == 1
    assert parsed.cfsr == 0x100
    assert parsed.sfsr == 0x8
    assert parsed.pc == 0x0001_2345
    assert parsed.lr == 0x0001_2340


def test_payload_status_truncated_frame_raises():
    with pytest.raises(ValueError):
        PayloadStatus().from_bytes(bytes(5))


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "power-on"),
        (1 << 0, "pin"),
        (1 << 1, "watchdog0"),
        (1 << 3, "soft-reset"),
        (1 << 4, "lockup"),
        ((1 << 1) | (1 << 3), "watchdog0+soft-reset"),
        (1 << 25, "watchdog1"),
        (1 << 30, "0x40000000"),
    ],
)
def test_decode_reset_reason(value, expected):
    assert decode_reset_reason(value) == expected


def test_decode_cfsr():
    assert decode_cfsr(0) == ""
    assert decode_cfsr(1 << 1) == "DACCVIOL"
    assert decode_cfsr(1 << 25) == "DIVBYZERO"
    assert decode_cfsr(1 << 20) == "STKOF"


def test_decode_sfsr():
    assert decode_sfsr(0) == ""
    # NS write into a secure region -> attribution unit violation
    assert decode_sfsr(1 << 3) == "AUVIOL"
    assert decode_sfsr(1 << 0) == "INVEP"


def test_device_info_matches_firmware_wire_size():
    # 178 bytes is the contract the firmware asserts on its own struct. If
    # this changes, swrmt_device_info_pkt_t must change with it.
    assert PayloadDeviceInfo().size == 178


def test_calibration_data_matches_firmware_wire_size():
    # swrmt_lh2_calibration_data_t: count, index, 3x3 float32, valid_mm[4],
    # site_name[16], calibration_id[8].
    assert PayloadCalibrationData().size == 84


def test_payload_device_info_v2_carries_the_site_and_id():
    payload = PayloadDeviceInfo(
        info_version=2,
        info_gen=7,
        lh2_homography_count=2,
        lh2_flags=0b111,
        lh2_site_name=b"c405-arena".ljust(16, b"\x00"),
        lh2_calibration_id=bytes.fromhex("ac893d2d85e3068c"),
    )
    raw = bytes(payload.to_bytes())
    assert len(raw) == 178

    parsed = PayloadDeviceInfo().from_bytes(raw)
    info = DeviceInfo.from_payload(parsed)
    assert info.info_version == 2
    assert info.lh2_site_name == "c405-arena"
    assert info.lh2_calibration_id == "ac893d2d85e3068c"
    assert info.lh2_flags & LH2_FLAG_FLOAT32


def test_payload_device_info_v1_parses_with_no_site_and_no_id():
    v2 = PayloadDeviceInfo(
        info_version=1,
        info_gen=7,
        lh2_homography_count=1,
        lh2_site_name=b"x" * 16,
        lh2_calibration_id=b"\x01" * 8,
    )
    v1 = bytes(v2.to_bytes())[:154]

    parsed = PayloadDeviceInfo().from_bytes(v1)
    info = DeviceInfo.from_payload(parsed)
    assert info.info_version == 1
    assert info.lh2_homography_count == 1
    assert parsed.lh2_site_name == bytes(16)
    assert info.lh2_site_name == ""
    assert info.lh2_calibration_id == ""


def test_an_all_zero_id_reads_as_none():
    parsed = PayloadDeviceInfo().from_bytes(
        bytes(PayloadDeviceInfo(info_version=2).to_bytes())
    )
    assert DeviceInfo.from_payload(parsed).lh2_calibration_id == ""


def test_payload_device_info_round_trip():
    payload = PayloadDeviceInfo(
        info_version=1,
        info_gen=42,
        boot_count=37,
        uptime_s=4324,
        bl_version=encode_string_field("0.9.0-3-g29e2704"),
        net_version=encode_string_field("0.9.0-3-g29e2704"),
        image_state=0,
        image_result=1,
        image_size=59360,
        image_digest=bytes.fromhex("3f9a2c81d4e5b607"),
        image_name=encode_string_field("lakers-sandbox.bin"),
        image_version=encode_string_field("0.9.0-12-g1a2b3c4"),
        lh2_homography_count=4,
        lh2_flags=0b11,
    )
    parsed = PayloadDeviceInfo().from_bytes(bytes(payload.to_bytes()))

    assert parsed.info_gen == 42
    assert parsed.boot_count == 37
    assert parsed.uptime_s == 4324
    assert parsed.image_size == 59360
    assert bytes(parsed.image_digest).hex() == "3f9a2c81d4e5b607"
    assert decode_string_field(parsed.image_name) == "lakers-sandbox.bin"
    assert decode_string_field(parsed.image_version) == "0.9.0-12-g1a2b3c4"
    assert decode_string_field(parsed.bl_version) == "0.9.0-3-g29e2704"
    assert parsed.lh2_homography_count == 4
    assert parsed.lh2_flags == 0b11


def test_payload_device_info_short_payload_raises():
    # A reply that is not the full record comes from a bot too old to talk to.
    # Zero-filling it invented a device record; raising lets the adapter drop
    # the frame and leaves the cached info untouched.
    with pytest.raises(ValueError):
        PayloadDeviceInfo().from_bytes(b"\x01\x05")


def test_payload_device_info_tolerates_trailing_bytes():
    # A device on a newer schema appends fields. The known prefix still parses
    # and the rest is ignored, so the host does not need its own truncation.
    full = bytes(PayloadDeviceInfo(info_version=1, info_gen=42).to_bytes())
    parsed = PayloadDeviceInfo().from_bytes(full + b"\xde\xad\xbe\xef")
    assert parsed.info_version == 1
    assert parsed.info_gen == 42


def test_string_fields_are_nul_padded_and_truncated():
    # Exactly 32 bytes on the wire, always NUL-terminated, so a name at or
    # past the cap cannot run into the field that follows it.
    assert len(encode_string_field("short")) == INFO_STRING_LEN
    assert encode_string_field("short")[5:] == bytes(INFO_STRING_LEN - 5)

    long_name = "x" * 100
    encoded = encode_string_field(long_name)
    assert len(encoded) == INFO_STRING_LEN
    assert encoded[-1] == 0
    assert decode_string_field(encoded) == "x" * (INFO_STRING_LEN - 1)

    # 31 characters is the longest that survives intact.
    edge = "y" * (INFO_STRING_LEN - 1)
    assert decode_string_field(encode_string_field(edge)) == edge


def test_payload_ota_start_carries_image_labels():
    payload = PayloadOTAStart(
        fw_length=1024,
        fw_chunk_count=8,
        image_name="move-and-blink.bin",
        image_version="2.0",
    )
    raw = payload.to_bytes()
    # 9 bytes of the original message plus the two 32-byte labels.
    assert len(raw) == 9 + 2 * INFO_STRING_LEN

    parsed = PayloadOTAStart().from_bytes(bytes(raw))
    assert parsed.fw_length == 1024
    assert parsed.version == 2
    assert decode_string_field(parsed.image_name) == "move-and-blink.bin"
    assert decode_string_field(parsed.image_version) == "2.0"


def test_payload_ota_start_defaults_to_empty_labels():
    # A flash with no labels still produces a well-formed packet; the device
    # reads empty strings and the host falls back to the digest.
    raw = PayloadOTAStart(fw_length=8, fw_chunk_count=1).to_bytes()
    assert len(raw) == 9 + 2 * INFO_STRING_LEN
    parsed = PayloadOTAStart().from_bytes(bytes(raw))
    assert decode_string_field(parsed.image_name) == ""


def test_payload_request_message_defaults_to_device_info():
    payload = PayloadRequestMessage()
    raw = payload.to_bytes()
    assert len(raw) == 2
    assert raw[0] == PayloadType.SWARMIT_DEVICE_INFO_RESP
    assert raw[1] == 0

    parsed = PayloadRequestMessage().from_bytes(bytes(raw))
    assert parsed.msg_id == PayloadType.SWARMIT_DEVICE_INFO_RESP


def test_image_digest_length_matches_firmware():
    assert IMAGE_DIGEST_LEN == 8


@pytest.mark.parametrize(
    "reset_reason,fault,expected",
    [
        (0, 0, "PowerOnReboot"),
        (1 << 0, 0, "PowerOnReboot"),
        (1 << 1, 0, "HardwareWatchdogReset"),  # WDT0: the crash deadman
        (1 << 25, 0, "SoftwareReset"),  # WDT1: only the stop command
        (1 << 3, 0, "SoftwareReset"),
        # A cabled flash sets ctrl-ap + SREQ + LOCKUP at once. Testing LOCKUP
        # first reported a freshly programmed device as watchdog-reset, which
        # is what the bench caught.
        (0x1C, 0, "SoftwareReset"),
        # A bare lockup: Matter has no value for it, and claiming a watchdog
        # fired when none did is worse than admitting the enum cannot say.
        (1 << 4, 0, "Unspecified"),
        # A latched fault wins over everything.
        (1 << 3, 1, "HardwareWatchdogReset"),
        # A watchdog timeout latches fault=3 without any fault being raised.
        # It is a genuine watchdog reset, so the Matter value is unchanged -
        # the distinction lives in format_reset_cause, not here.
        (1 << 1, 3, "HardwareWatchdogReset"),
    ],
)
def test_boot_reason_mapping(reset_reason, fault, expected):
    assert boot_reason(reset_reason, fault).name == expected


def test_boot_reason_is_derived_not_transmitted():
    # The device does not send it: everything the mapping needs already rides
    # the status frame, so a fix is a host change rather than a reflash.
    assert not hasattr(PayloadDeviceInfo(), "boot_reason")


def test_watchdog_timeout_rides_the_existing_crash_report():
    """A hang reuses fault, pc and lr rather than adding fields of its own.

    Spending a fault enumerator keeps the two cases - crashed and hung - in
    one shape, so everything that reads a crash report reads both without
    branching on which kind it is.
    """
    payload = PayloadStatus(
        device=1,
        status=2,
        reset_reason=0x2,  # watchdog0
        fault=FaultType.WatchdogTimeout.value,
        from_ns=1,
        pc=0x0001_3A4E,
        lr=0x0001_39C0,
    )
    raw = payload.to_bytes()
    assert len(raw) == STATUS_BASE_SIZE + CRASH_REPORT_SIZE + INFO_GEN_SIZE

    parsed = PayloadStatus().from_bytes(bytes(raw))
    assert parsed.fault == 3
    assert parsed.from_ns == 1
    assert parsed.pc == 0x0001_3A4E
    assert parsed.lr == 0x0001_39C0
    # No fault was raised, so the fault-status registers stay empty.
    assert parsed.cfsr == 0
    assert parsed.sfsr == 0


@pytest.mark.parametrize(
    "psr,expected",
    [
        (0x0100_0000, "thread"),  # T bit set, IPSR 0: ordinary app code
        (0x0100_0003, "HardFault"),
        (0x0100_000F, "SysTick"),
        (0x0100_001A, "IRQ 10"),  # 26 - 16
        (0x0000_0009, "exception 9"),  # reserved, reported honestly
    ],
)
def test_decode_ipsr(psr, expected):
    assert decode_ipsr(psr) == expected


def test_battery_pct_reads_the_v3_supercap_as_stored_energy():
    """A straight voltage ratio reads 20% on a v3 that can no longer move.

    The pack is a 3.0 V supercapacitor that browns out at 0.6 V, and a
    capacitor holds energy as 1/2 C V^2, so the usable fraction is the span
    between the squares.
    """
    from swarmit.testbed.protocol import DeviceType, battery_pct

    v3 = DeviceType.DotBotV3
    assert battery_pct(v3, 3000) == 100
    assert battery_pct(v3, 600) == 0  # brownout is empty, not 20%
    assert battery_pct(v3, 400) == 0  # never negative
    assert battery_pct(v3, 2300) == 57
    assert battery_pct(v3, 1500) == 21  # the warning line is a fifth left


def test_battery_pct_leaves_unprofiled_devices_on_the_historical_reading():
    """DotBotV2 is battery-backed and needs measured voltages of its own."""
    from swarmit.testbed.protocol import DeviceType, battery_pct

    assert battery_pct(DeviceType.DotBotV2, 2300) == 76
    assert battery_pct(DeviceType.Unknown, 3000) == 100


def test_battery_level_bands_match_the_bootloader_led():
    """The bootloader drives its status LED off the same two thresholds.

    device/bootloader/Source/main.c uses `> BATTERY_VOLTAGE_FULL` (2900) for
    blue and `> BATTERY_VOLTAGE_WARNING` (1500) for green. A bot showing a
    blue LED beside an "ok" host reading is a confusing pair, so the
    boundaries are asserted exactly, not approximately.
    """
    from swarmit.testbed.protocol import DeviceType, battery_level

    v3 = DeviceType.DotBotV3
    assert battery_level(v3, 2901) == "full"
    assert battery_level(v3, 2900) == "ok"  # not > 2900: the LED is green here
    assert battery_level(v3, 1501) == "ok"
    assert battery_level(v3, 1500) == "low"  # not > 1500: the LED is red here
