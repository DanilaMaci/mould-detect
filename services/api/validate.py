"""Input validation for services/api: turns untrusted JSON and query strings into clean values, or a list of problems.
Pure functions, no I/O (tested in test_validate.py). The limits mirror the CHECK constraints of
supabase/migrations/, so a row the API accepts would also be accepted by Supabase.
"""
import json
from datetime import datetime, timedelta, timezone

# column -> (type, lowest, highest, required). Keys and limits as in indoor_readings.
FIELDS = {
    "temp_c":         (float, -40, 85, True),
    "rh":             (float, 0, 100, True),
    "press_hpa":      (float, 300, 1100, True),
    "rssi_dbm":       (int, -120, 0, False),
    "co2_ppm":        (int, 0, 40000, False),
    "scd_temp_c":     (float, -10, 60, False),
    "scd_rh":         (float, 0, 100, False),
    "wall_temp_c":    (float, -55, 125, False),
    "outdoor_temp_c": (float, -55, 125, False),
    "window_open":    (bool, None, None, False),
    "door_open":      (bool, None, None, False),
}
MAX_FUTURE = timedelta(minutes=5)     # device clock slightly ahead is fine, a wrong year is not
MAX_PAST = timedelta(days=7)          # backlog the firmware may send after an outage (stage 7)
MAX_LIMIT = 5000


def parse_json(body):
    """Bytes -> dict. NaN/Infinity are rejected (Python's json accepts them by default; JSON does not)."""
    def no_constants(name):
        raise ValueError(f"{name} is not valid JSON")
    data = json.loads(body.decode("utf-8"), parse_constant=no_constants)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def reading(data, device_id, now):
    """Validate one reading from `device_id` (taken from its token, not trusted from the body).
    Returns (row, problems): row is a dict ready for the database when problems is empty."""
    problems = []
    row = {"device_id": device_id}
    for key in data:
        if key not in FIELDS and key not in ("device_id", "measured_at"):
            problems.append(f"{key}: unknown field")
    if "device_id" in data and data["device_id"] != device_id:
        problems.append("device_id: does not match the token")
    for name, (kind, lo, hi, required) in FIELDS.items():
        value = data.get(name)
        if value is None:
            if required:
                problems.append(f"{name}: required")
            row[name] = None
            continue
        # bool is a subclass of int in Python: True must not pass as 1 °C, and 1 must not pass as "open"
        if kind is bool:
            ok = isinstance(value, bool)
        elif kind is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not ok:
            problems.append(f"{name}: expected {kind.__name__}")
        elif lo is not None and not lo <= value <= hi:
            problems.append(f"{name}: {value} outside {lo}..{hi}")
        else:
            row[name] = float(value) if kind is float else value
    measured = data.get("measured_at")
    if measured is None:
        row["measured_at"] = now
    else:
        t = timestamp(measured)
        if t is None:
            problems.append("measured_at: expected an ISO 8601 time with a time zone")
        elif not now - MAX_PAST <= t <= now + MAX_FUTURE:
            problems.append("measured_at: more than 5 min ahead or 7 days behind the server clock")
        else:
            row["measured_at"] = t
    return row, problems


def timestamp(value):
    """ISO 8601 with a time zone -> aware UTC datetime, else None."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None


def query(params, now):
    """Query string (dict of lists, from urllib.parse.parse_qs) for GET endpoints -> (clean dict, problems).
    since/until default to the last 24 h; limit 1..MAX_LIMIT, default 1000."""
    problems, out = [], {}
    for key in params:
        if key not in ("device_id", "since", "until", "limit", "hourly"):
            problems.append(f"{key}: unknown parameter")
    one = {k: v[-1] for k, v in params.items()}
    out["device_id"] = one.get("device_id")
    if out["device_id"] is not None and not (0 < len(out["device_id"]) <= 32):
        problems.append("device_id: 1..32 characters")
    for key, default in (("since", now - timedelta(days=1)), ("until", now)):
        if key in one:
            t = timestamp(one[key])
            if t is None:
                problems.append(f"{key}: expected an ISO 8601 time with a time zone")
            out[key] = t
        else:
            out[key] = default
    try:
        out["limit"] = int(one.get("limit", 1000))
        if not 1 <= out["limit"] <= MAX_LIMIT:
            raise ValueError
    except ValueError:
        problems.append(f"limit: whole number 1..{MAX_LIMIT}")
    out["hourly"] = one.get("hourly") in ("1", "true")
    return out, problems
