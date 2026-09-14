import pytest

from swarmit.testbed.helpers import (
    MATRIX_BYTES,
    homography_as_bytes,
    load_toml_config,
    read_calibration,
    read_lh2_calibration_payload,
    reference_points,
)

TEST_CONFIG_TOML = """
adapter = "edge"
serial_port = "/dev/ttyACM0"
baudrate = 1000000
devices = ""
"""

# A schema 2 calibration, in the shape PyDotBot's writer emits. The same
# fixture is pinned on that side, so the two packers cannot drift.
CALIBRATION_TOML = """\
schema_version = 2

[metadata]
created_at = "2026-09-10T09:12:00Z"
id = "3f9a1c07e2b845d6"
robot = "dotbot-v3"

[site]
name = "inria-aio-c"
anchor = "the arena's top-left corner, against the door wall of C405"

[validity]
valid_mm = [0, 0, 4000, 4500]

[[placement]]
index = 0
at = "arena:corners"
points_mm = [[50.0, 20.0], [2000.0, 20.0], [50.0, 2000.0], [2000.0, 2000.0]]
captured_at = "2026-09-10T09:10:41Z"
samples = [
  { station = 0, point = 0, count1 = [41290], count2 = [51728] },
]

[[station]]
index = 0
solved_from = "direct"
points = 4
residual_mm = 0.0
homography = [[1523.4, -38.2, 1012.7], [41.9, 1531.8, 988.3], [0.2134, -0.0871, 1.0]]
"""

# The fixture's homography through the int32 x 1e3 shim: 1523400, -38200,
# 1012700, 41900, 1531800, 988300, 213, -87, 1000 as little-endian int32.
# PyDotBot pins the same bytes for the same matrix.
EXPECTED_MATRIX_BYTES = bytes.fromhex(
    "c83e1700c86affffdc730f00"
    "aca30000985f17008c140f00"
    "d5000000a9ffffffe8030000"
)


def _write(tmp_path, text, name="calibration.toml"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_load_toml_config(tmp_path):
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text(TEST_CONFIG_TOML)
    cfg = load_toml_config(str(cfg_path))
    assert cfg["adapter"] == "edge"
    assert cfg["serial_port"] == "/dev/ttyACM0"
    assert cfg["baudrate"] == 1000000
    assert cfg["devices"] == ""


def test_load_toml_config_empty():
    cfg = load_toml_config("")
    assert cfg == {}


def test_schema_2_matrices_pack_to_the_expected_int32_payload(tmp_path):
    """Byte-for-byte against the int32 x 1e3 encoding PyDotBot's packer pins."""
    payload = read_lh2_calibration_payload(_write(tmp_path, CALIBRATION_TOML))

    assert payload == bytes([1]) + EXPECTED_MATRIX_BYTES
    assert len(payload) == 1 + MATRIX_BYTES


def test_the_shim_truncates_towards_zero_and_zeroes_on_overflow():
    """Quantisation is int32 x 1e3 truncated, and a value too large zeroes the record."""
    packed = homography_as_bytes([1.0009, -1.0009] + [0.0] * 7)

    assert packed[0:4] == (1000).to_bytes(4, "little", signed=True)
    assert packed[4:8] == (-1000).to_bytes(4, "little", signed=True)
    assert homography_as_bytes([1e9] + [0.0] * 8) == bytes(MATRIX_BYTES)


def test_schema_1_file_is_refused(tmp_path):
    path = _write(tmp_path, 'schema_version = 1\n[calibration]\ndata_hex = "00"\n')
    with pytest.raises(ValueError, match="schema_version 1"):
        read_lh2_calibration_payload(path)


def test_reference_points_are_the_placements_points(tmp_path):
    """The dashboard's crosses come from the placements, not from the areas."""
    data = read_calibration(_write(tmp_path, CALIBRATION_TOML))
    assert reference_points(data) == [
        [50.0, 20.0],
        [2000.0, 20.0],
        [50.0, 2000.0],
        [2000.0, 2000.0],
    ]


def test_changing_the_areas_leaves_the_calibration_payload_identical(tmp_path):
    """An area is a view: a settings change never touches what a bot receives."""
    from swarmit.testbed.controller import ControllerSettings
    from swarmit.testbed.webserver import AreaModel, SettingsResponse

    path = _write(tmp_path, CALIBRATION_TOML)
    before = read_lh2_calibration_payload(path)

    settings = ControllerSettings(network_id=1)
    narrow = SettingsResponse(
        network_id=settings.network_id,
        areas=[AreaModel(x=r[0], y=r[1], w=r[2], h=r[3]) for r in settings.areas],
        reference_points=reference_points(read_calibration(path)),
        auth_mode="none",
    )
    settings.areas = [[0, 2000, 2000, 2000], [2000, 2610, 1330, 1390]]
    wide = SettingsResponse(
        network_id=settings.network_id,
        areas=[AreaModel(x=r[0], y=r[1], w=r[2], h=r[3]) for r in settings.areas],
        reference_points=reference_points(read_calibration(path)),
        auth_mode="none",
    )

    assert narrow.areas != wide.areas
    assert narrow.reference_points == wide.reference_points
    assert read_lh2_calibration_payload(path) == before
