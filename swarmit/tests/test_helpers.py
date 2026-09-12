import struct

import pytest

from swarmit.testbed.helpers import (
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

EXPECTED_MATRIX = [
    1523.4,
    -38.2,
    1012.7,
    41.9,
    1531.8,
    988.3,
    0.2134,
    -0.0871,
    1.0,
]


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


def test_schema_2_matrices_pack_to_the_expected_float32_payload(tmp_path):
    """Byte-for-byte against the float32 encoding PyDotBot's packer pins."""
    payload = read_lh2_calibration_payload(_write(tmp_path, CALIBRATION_TOML))

    assert payload == bytes([1]) + struct.pack("<9f", *EXPECTED_MATRIX)
    assert len(payload) == 1 + 36


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
