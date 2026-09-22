import pytest

from swarmit.testbed.helpers import (
    load_toml_config,
    read_calibration,
    read_lh2_calibration_payload,
    reference_points,
)
from swarmit.tests.lh2_wire_fixture import FIXTURE_TOML, MESSAGE_HEX

TEST_CONFIG_TOML = """
adapter = "edge"
serial_port = "/dev/ttyACM0"
baudrate = 1000000
devices = ""
"""

# A schema 2 calibration, for the tests that read its tables.
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


def test_the_calibration_messages_are_pinned(tmp_path):
    """Byte for byte the messages PyDotBot's packer pins for the same file."""
    payload = read_lh2_calibration_payload(_write(tmp_path, FIXTURE_TOML))

    assert payload == b"".join(bytes.fromhex(h) for h in MESSAGE_HEX)
    assert len(payload) == 2 * 84


def test_a_gap_in_the_station_numbering_is_refused(tmp_path):
    gapped = FIXTURE_TOML.replace(
        "index = 1\nsolved_from", "index = 2\nsolved_from"
    )
    with pytest.raises(ValueError, match="without gaps"):
        read_lh2_calibration_payload(_write(tmp_path, gapped))


@pytest.mark.parametrize(
    "edit, match",
    [
        (
            ('name = "c405-arena"', 'name = "a-name-too-long-for-16"'),
            "1 to 16",
        ),
        (('id = "ac893d2d85e3068c"', 'id = "ac89"'), "shorter than 16"),
        (
            ("valid_mm = [0, 0, 3330, 4000]", "valid_mm = [0, 0, -1, 4000]"),
            "valid_mm",
        ),
    ],
    ids=["long-site", "short-id", "negative-valid-mm"],
)
def test_site_fields_a_robot_cannot_store_are_refused(tmp_path, edit, match):
    with pytest.raises(ValueError, match=match):
        read_lh2_calibration_payload(
            _write(tmp_path, FIXTURE_TOML.replace(*edit))
        )


def test_a_declared_id_is_sent_as_is(tmp_path):
    """The low-level packer trusts metadata.id; PyDotBot is where it is checked."""
    edited = FIXTURE_TOML.replace(
        'id = "ac893d2d85e3068c"', 'id = "0123456789abcdef"'
    )
    payload = read_lh2_calibration_payload(_write(tmp_path, edited))
    assert payload[76:84] == bytes.fromhex("0123456789abcdef")


def test_schema_1_file_is_refused(tmp_path):
    path = _write(
        tmp_path, 'schema_version = 1\n[calibration]\ndata_hex = "00"\n'
    )
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
        areas=[
            AreaModel(x=r[0], y=r[1], w=r[2], h=r[3]) for r in settings.areas
        ],
        reference_points=reference_points(read_calibration(path)),
        auth_mode="none",
    )
    settings.areas = [[0, 2000, 2000, 2000], [2000, 2610, 1330, 1390]]
    wide = SettingsResponse(
        network_id=settings.network_id,
        areas=[
            AreaModel(x=r[0], y=r[1], w=r[2], h=r[3]) for r in settings.areas
        ],
        reference_points=reference_points(read_calibration(path)),
        auth_mode="none",
    )

    assert narrow.areas != wide.areas
    assert narrow.reference_points == wide.reference_points
    assert read_lh2_calibration_payload(path) == before
