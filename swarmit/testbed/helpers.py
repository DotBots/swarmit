import struct
import tomllib

from swarmit.testbed.protocol import (
    LH2_CALIBRATION_ID_LEN,
    LH2_SITE_NAME_LEN,
    PayloadCalibrationData,
)

# Bump in lockstep with the writer in PyDotBot's
# dotbot/calibration/lighthouse2.py (CALIBRATION_SCHEMA_VERSION).
CALIBRATION_SCHEMA_VERSION = 2

LH2_BASESTATION_COUNT_MAX = 16
# What PyDotBot's reader assumes for a file without [validity]; keep in step.
VALID_MM_DEFAULT = (0, 0, 4000, 4500)
SITE_DEFAULT = "default"


def load_toml_config(path):
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def read_calibration(path):
    """Parse a schema 2 LH2 calibration file into its tables.

    Raises ValueError for bad TOML, an unknown schema version, or a file with
    no solved station, so the CLI can report it rather than passing garbage
    to the controller.
    """
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: invalid TOML ({exc})") from exc

    schema = data.get("schema_version", 0)
    if schema != CALIBRATION_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported calibration schema_version {schema} "
            f"(this build supports {CALIBRATION_SCHEMA_VERSION})"
        )

    stations = data.get("station")
    if not stations:
        raise ValueError(f"{path}: no [[station]] table to send")
    if len(stations) > LH2_BASESTATION_COUNT_MAX:
        raise ValueError(
            f"{path}: {len(stations)} stations exceeds the LH2 limit "
            f"({LH2_BASESTATION_COUNT_MAX})"
        )
    return data


def reference_points(data):
    """Every placement point of a calibration, in frame millimetres.

    The dashboard draws its calibration crosses at these, so they travel
    beside the areas and never derived from them.
    """
    points = []
    for placement in data.get("placement", []):
        points.extend(
            [float(point[0]), float(point[1])]
            for point in placement["points_mm"]
        )
    return points


def site_fields(data, path=""):
    """valid_mm, site name and calibration id, as `PayloadCalibrationData` fields.

    PyDotBot's `site_fields_as_bytes` packs the same bytes; the fixture test
    in each repo pins them for the same file. metadata.id is packed as the
    file declares it, never checked against the content; PyDotBot refuses a
    file whose id is not its content's own.
    """
    valid_mm = [
        int(v)
        for v in data.get("validity", {}).get("valid_mm", VALID_MM_DEFAULT)
    ]
    if (
        len(valid_mm) != 4
        or any(v < 0 or v > 0xFFFFFFFF for v in valid_mm)
        or valid_mm[0] > valid_mm[2]
        or valid_mm[1] > valid_mm[3]
    ):
        raise ValueError(
            f"{path}: valid_mm must be [x_min, y_min, x_max, y_max] in "
            f"uint32 mm, got {valid_mm}"
        )
    name = data.get("site", {}).get("name", SITE_DEFAULT)
    try:
        raw_name = name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{path}: site name {name!r} is not ASCII") from exc
    if not raw_name or len(raw_name) > LH2_SITE_NAME_LEN:
        raise ValueError(
            f"{path}: site name {name!r} must be 1 to {LH2_SITE_NAME_LEN} "
            "characters to reach a robot"
        )
    calibration_id = str(data.get("metadata", {}).get("id", ""))
    try:
        raw_id = bytes.fromhex(calibration_id[: 2 * LH2_CALIBRATION_ID_LEN])
    except ValueError as exc:
        raise ValueError(
            f"{path}: metadata.id {calibration_id!r} is not hex"
        ) from exc
    if len(raw_id) != LH2_CALIBRATION_ID_LEN:
        raise ValueError(
            f"{path}: metadata.id {calibration_id!r} is shorter than "
            f"{2 * LH2_CALIBRATION_ID_LEN} hex characters"
        )
    return {
        "valid_x_min": valid_mm[0],
        "valid_y_min": valid_mm[1],
        "valid_x_max": valid_mm[2],
        "valid_y_max": valid_mm[3],
        "site_name": raw_name.ljust(LH2_SITE_NAME_LEN, b"\x00"),
        "calibration_id": raw_id,
    }


def read_lh2_calibration_payload(path):
    """The calibration messages for `path`, one 84-byte message per station.

    Built at send time from `[[station]].homography` and the site fields.
    The receiver trusts slots 0 to count - 1, so stations must be numbered
    from zero without gaps.
    """
    data = read_calibration(path)
    stations = sorted(data["station"], key=lambda s: int(s["index"]))
    indices = [int(s["index"]) for s in stations]
    if indices != list(range(len(stations))):
        got = ", ".join(str(i) for i in indices)
        raise ValueError(
            f"{path}: stations must be numbered from zero without gaps to be "
            f"pushed, got {got}"
        )
    fields = site_fields(data, path)
    payload = bytearray()
    for station in stations:
        flat = [float(v) for row in station["homography"] for v in row]
        if len(flat) != 9:
            raise ValueError(
                f"{path}: station {station['index']} homography is not 3x3"
            )
        payload += PayloadCalibrationData(
            homography_count=len(stations),
            homography_index=int(station["index"]),
            homography=struct.pack("<9f", *flat),
            **fields,
        ).to_bytes()
    return bytes(payload)
