import struct
import tomllib

# Bump in lockstep with the writer in PyDotBot's
# dotbot/calibration/lighthouse2.py (CALIBRATION_SCHEMA_VERSION).
CALIBRATION_SCHEMA_VERSION = 2

LH2_BASESTATION_COUNT_MAX = 16
# 1-byte station count, then one 36-byte record per station: nine IEEE 754
# float32, little-endian, row-major. Mirrors PyDotBot's
# dotbot/calibration/wire.py, and a fixture test in each repo pins the same
# bytes for the same file.
_MATRIX = struct.Struct("<9f")
MATRIX_BYTES = _MATRIX.size


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
    beside the bounds and never derived from them.
    """
    points = []
    for placement in data.get("placement", []):
        points.extend(
            [float(point[0]), float(point[1])] for point in placement["points_mm"]
        )
    return points


def read_lh2_calibration_payload(path):
    """Return the LH2 calibration wire payload for `path`.

    Built at send time from `[[station]].homography`, station indices in
    order.
    """
    data = read_calibration(path)
    stations = sorted(data["station"], key=lambda s: int(s["index"]))
    payload = bytearray([len(stations)])
    for station in stations:
        flat = [float(v) for row in station["homography"] for v in row]
        if len(flat) != 9:
            raise ValueError(
                f"{path}: station {station['index']} homography is not 3x3"
            )
        payload += _MATRIX.pack(*flat)
    return bytes(payload)
