import tomllib

# Bump in lockstep with the writer in PyDotBot's
# dotbot/calibration/lighthouse2.py (CALIBRATION_SCHEMA_VERSION).
CALIBRATION_SCHEMA_VERSION = 2

LH2_BASESTATION_COUNT_MAX = 16
# 1-byte station count, then one 36-byte record per station: nine
# little-endian int32, row-major, each the value times 1e3.
MATRIX_BYTES = 9 * 4


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
            [float(point[0]), float(point[1])] for point in placement["points_mm"]
        )
    return points


def homography_as_bytes(flat):
    """THE SHIM: pack a homography as nine int32, the value times 1e3, truncated.

    The only place a homography is quantised, and it exists solely so a
    schema 2 calibration can reach firmware that still reads the int32 x 1e3
    encoding (`protocol_lh2_homography_t` in dotbot-libs). It is deleted in
    the float32 firmware wave; until then nothing sends float32 to a bot.

    PyDotBot's `homography_as_bytes` must stay byte-for-byte identical to
    this, down to the all-zero fallback on overflow; the fixture test in
    each repo pins the same bytes for the same matrix.
    """
    matrix_bytes = bytearray()
    try:
        for bytes_block in [
            int(value * 1e3).to_bytes(4, "little", signed=True)
            for value in flat
        ]:
            matrix_bytes += bytes_block
    except Exception:  # noqa: BLE001 - defensive fallback for overflow
        matrix_bytes = bytearray(MATRIX_BYTES)
    return bytes(matrix_bytes)


def read_lh2_calibration_payload(path):
    """Return the LH2 calibration wire payload for `path`.

    Built at send time from `[[station]].homography`, station indices in
    order, quantised through `homography_as_bytes`.
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
        payload += homography_as_bytes(flat)
    return bytes(payload)
