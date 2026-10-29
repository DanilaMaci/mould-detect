"""Pipeline checks for services/monitor: pure functions from a snapshot of the data to check results. No I/O, so
every rule is unit-tested with synthetic rows (test_checks.py).

Statuses: ok, off (sensor never fitted), warn, fail, unknown (nothing to judge: Supabase unreachable, or the node is
not sending). A silent node turns its sensor checks unknown instead of failing them too: one cause, one alert.
"""
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "jobs"))
from fetch_weather import missing_hours   # noqa: E402  (jobs/fetch_weather.py)

OK, OFF, WARN, FAIL, UNKNOWN = "ok", "off", "warn", "fail", "unknown"
SEVERITY = {OK: 0, OFF: 0, WARN: 1, FAIL: 2}   # unknown has none: it never raises or clears an alert

MIN = timedelta(minutes=1)

# The room node sends a row every minute (firmware SEND_INTERVAL_MS) plus one per button press
SILENT_WARN = 5 * MIN
SILENT_FAIL = 15 * MIN

# Plausible range of the newest value. Outside it the sensor or its wiring is faulty, not the weather. Narrower than
# the database CHECK constraints, which only stop impossible values.
PLAUSIBLE = {
    "temp_c":         (5, 40),       # BME280, heated room
    "rh":             (5, 99),       # 100 % = wet or failed sensor
    "press_hpa":      (900, 1080),   # station pressure, below ~900 m altitude
    "co2_ppm":        (350, 10000),  # below outdoor air (~420 ppm) = miscalibrated
    "scd_temp_c":     (5, 40),
    "scd_rh":         (5, 99),
    "wall_temp_c":    (-10, 35),     # inside surface of an outside wall; 85.0 = DS18B20 power-on value
    "outdoor_temp_c": (-40, 45),
}

# A column whose value has not changed at all for this long is stuck (frozen bus, cached value). The DS18B20 probes
# are left out: at 0.0625 °C steps a heated wall can honestly hold one value for hours overnight, and a failed probe
# shows up as null (probe checks) or 85 °C (ranges) instead.
STUCK_AFTER = {"temp_c": 30 * MIN, "rh": 30 * MIN, "press_hpa": 30 * MIN, "co2_ppm": 30 * MIN,
               "scd_temp_c": 30 * MIN, "scd_rh": 30 * MIN}
WINDOW = max(STUCK_AFTER.values())   # how much recent data the monitor fetches

# Optional sensors: the column that is null while the sensor is missing -> name in the check id
PROBES = {"co2_ppm": "scd40", "wall_temp_c": "wall_probe", "outdoor_temp_c": "outdoor_probe"}
PROBE_LOST_AFTER = 10 * MIN
PROBE_LOOKBACK = timedelta(days=30)  # no value in this long = not fitted (off), not lost

WEATHER_GAP_WINDOW = timedelta(hours=72)
WEATHER_STALE_AFTER = timedelta(hours=3)   # serve.py syncs hourly while it runs


@dataclass(frozen=True)
class Result:
    check: str     # stable id, e.g. "node1/silent"
    status: str
    message: str


@dataclass
class Snapshot:
    """What one monitor run fetched. Timestamps are timezone-aware datetimes."""
    devices: list                                    # expected device ids
    error: str | None = None                         # Supabase query failed: every data check is unknown
    last_received: dict = field(default_factory=dict)   # device -> received_at of its newest row, None = no rows
    rows: list = field(default_factory=list)            # expected nodes' rows of the last WINDOW, oldest first
    other_devices: set = field(default_factory=set)     # device ids of the last WINDOW that are not expected
    probe_seen: dict = field(default_factory=dict)      # (device, column) -> newest non-null measured_at, None = never
    weather_hours: set = field(default_factory=set)     # observed_at of stored open-meteo hours
    weather_fetched_at: datetime | None = None          # newest fetched_at = last weather sync
    http: dict = field(default_factory=dict)            # target name -> (status code or None, error text or None)


def fmt_age(td):
    s = td.total_seconds()
    if -60 < s < 0:   # node clock slightly ahead of this machine: read as now; a larger skew stays visible
        s = 0
    if s < 120:
        return f"{s:.0f} s"
    if s < 7200:
        return f"{s / 60:.0f} min"
    if s < 172800:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} d"


def node_silent(device, last_received, now):
    check = f"{device}/silent"
    if last_received is None:
        return Result(check, FAIL, "no rows from this node")
    age = now - last_received
    status = FAIL if age >= SILENT_FAIL else WARN if age >= SILENT_WARN else OK
    return Result(check, status, f"last row {fmt_age(age)} ago")


def out_of_range(device, rows):
    """Newest row of the device against PLAUSIBLE. Null columns (sensor missing) are the probe checks' business."""
    latest = rows[-1]
    bad = [f"{col} {latest[col]:g} outside {lo:g}..{hi:g}" for col, (lo, hi) in PLAUSIBLE.items()
           if latest.get(col) is not None and not lo <= latest[col] <= hi]
    return Result(f"{device}/ranges", FAIL if bad else OK, "; ".join(bad) or "newest values plausible")


def stuck_values(device, rows, now):
    """Columns with one single value over their whole STUCK_AFTER window. Judged only when the window is covered:
    at least one value per two minutes, the oldest from the first fifth of the window."""
    stuck = []
    for col, after in STUCK_AFTER.items():
        recent = [(r["measured_at"], r[col]) for r in rows if r.get(col) is not None and r["measured_at"] >= now - after]
        if len(recent) < after / MIN / 2 or recent[0][0] > now - after * 0.8:
            continue
        if len({v for _, v in recent}) == 1:
            stuck.append(f"{col} at {recent[0][1]:g} for {fmt_age(now - recent[0][0])}")
    return Result(f"{device}/stuck", WARN if stuck else OK, "; ".join(stuck) or "values changing")


def probe(device, column, last_seen, now):
    check = f"{device}/{PROBES[column]}"
    if last_seen is None:
        return Result(check, OFF, f"no {column} in {PROBE_LOOKBACK.days} days: not fitted")
    age = now - last_seen
    if age > PROBE_LOST_AFTER:
        return Result(check, FAIL, f"no {column} for {fmt_age(age)} while the node is sending")
    return Result(check, OK, f"{column} {fmt_age(age)} ago")


def unexpected_devices(device_ids):
    """Rows from device ids nobody configured: a misconfigured node, or someone using the public insert key. Ids are
    written by whoever inserts, so they are cut to 32 safe characters before they reach a page or a phone."""
    others = sorted({re.sub(r"[^A-Za-z0-9_.-]", "?", d[:32]) for d in device_ids})
    if not others:
        return Result("devices/unexpected", OK, "only expected device ids")
    shown = ", ".join(others[:5]) + (" ..." if len(others) > 5 else "")
    return Result("devices/unexpected", WARN, f"{len(others)} unexpected device id(s) in the last {fmt_age(WINDOW)}: {shown}")


def weather_gaps(hours, now):
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    gaps = missing_hours(hours, this_hour - WEATHER_GAP_WINDOW, this_hour)
    if not gaps:
        return Result("weather/gaps", OK, f"no missing hours in the last {fmt_age(WEATHER_GAP_WINDOW)}")
    return Result("weather/gaps", WARN, f"{len(gaps)} missing hour(s) in the last {fmt_age(WEATHER_GAP_WINDOW)}, "
                                        f"first {gaps[0]:%Y-%m-%d %H:00} UTC")


def weather_fresh(fetched_at, now):
    if fetched_at is None:
        return Result("weather/fresh", WARN, "weather_hourly is empty")
    age = now - fetched_at
    status = WARN if age > WEATHER_STALE_AFTER else OK
    return Result("weather/fresh", status, f"last sync {fmt_age(age)} ago" + (" (serve.py not running?)" if status == WARN else ""))


def http_target(name, code, error):
    if code is None:
        return Result(f"http/{name}", FAIL, error or "no answer")
    return Result(f"http/{name}", OK if code < 400 else FAIL, f"HTTP {code}")


def evaluate(snap, now):
    """All results for one run. The same check ids come out whether or not Supabase answered."""
    results = [Result("supabase", FAIL, snap.error) if snap.error else Result("supabase", OK, "queries answered")]
    for device in snap.devices:
        rows = [r for r in snap.rows if r.get("device_id") == device]
        silent = None if snap.error else node_silent(device, snap.last_received.get(device), now)
        alive = silent is not None and silent.status == OK and rows
        why = "Supabase not answering" if snap.error else "node not sending"
        results.append(silent or Result(f"{device}/silent", UNKNOWN, why))
        results.append(out_of_range(device, rows) if alive else Result(f"{device}/ranges", UNKNOWN, why))
        results.append(stuck_values(device, rows, now) if alive else Result(f"{device}/stuck", UNKNOWN, why))
        for col, name in PROBES.items():
            results.append(probe(device, col, snap.probe_seen.get((device, col)), now) if alive
                           else Result(f"{device}/{name}", UNKNOWN, why))
    if snap.error:
        results += [Result(c, UNKNOWN, "Supabase not answering")
                    for c in ("devices/unexpected", "weather/gaps", "weather/fresh")]
    else:
        results += [unexpected_devices(snap.other_devices), weather_gaps(snap.weather_hours, now),
                    weather_fresh(snap.weather_fetched_at, now)]
    results += [http_target(name, code, error) for name, (code, error) in snap.http.items()]
    return results


# --- Explanations for the status page: what each check watches, the rule, and what to do --------------------------

def _ranges():
    return ", ".join(f"{col} {lo:g}..{hi:g}" for col, (lo, hi) in PLAUSIBLE.items())


def _stuck():
    return ", ".join(f"{col} {fmt_age(after)}" for col, after in STUCK_AFTER.items())


EXPLAIN = {
    "silent": ("Is the node still sending? It posts a row every minute, plus one per button press.",
               lambda: f"warn when the newest row is {fmt_age(SILENT_WARN)} old, fail at {fmt_age(SILENT_FAIL)}. "
                       "While a node is silent its sensor checks show unknown, so one outage gives one alert.",
               "Look at the node's LEDs / serial log: power, Wi-Fi, or Supabase rejecting the POST (HTTP status in "
               "the log)."),
    "ranges": ("Are the newest values physically plausible for this room? Values outside mean a faulty sensor or "
               "wire, not weather.",
               lambda: f"fail when the newest row has a value outside: {_ranges()}. Empty columns are ignored here.",
               "Check the wiring of the sensor named in the detail. 85 °C on a DS18B20 means it was read before its "
               "first conversion (power or timing)."),
    "stuck": ("Has a value stopped changing? Real sensors always jitter a little; a frozen value means a hung bus or "
              "firmware re-sending an old reading.",
              lambda: f"warn when a column had one single value for its whole window: {_stuck()}. Only judged when "
                      "the window is covered by data (at least one value per 2 min). DS18B20 probes are not judged "
                      "here (a wall can hold one 0.0625 °C step for hours).",
              "Reboot the node; if it comes back, look for I2C errors in the serial log."),
    "scd40": ("Is the SCD-40 (CO2 sensor) still delivering? Its columns are empty when it is missing or failed.",
              lambda: f"fail when no co2_ppm for {fmt_age(PROBE_LOST_AFTER)} while the node sends; off when there "
                      f"was none in {PROBE_LOOKBACK.days} days (never fitted).",
              "Check the I2C wires (boot scan should list 0x62)."),
    "wall_probe": ("Is the wall-surface DS18B20 still delivering? Needed for the surface humidity / mould risk.",
                   lambda: f"fail when no wall_temp_c for {fmt_age(PROBE_LOST_AFTER)} while the node sends; off when "
                           f"there was none in {PROBE_LOOKBACK.days} days.",
                   "Check the probe's joint and the 4.7 kOhm pull-up on GPIO4."),
    "outdoor_probe": ("Is the outdoor DS18B20 still delivering?",
                      lambda: f"fail when no outdoor_temp_c for {fmt_age(PROBE_LOST_AFTER)} while the node sends; "
                              f"off when there was none in {PROBE_LOOKBACK.days} days (not fitted yet).",
                      "Check the cable through the window hinge side."),
    "devices/unexpected": ("Are rows arriving from device ids that are not configured? Either a node with a wrong "
                           "DEVICE_ID, or someone else using the public insert key (it accepts any row today).",
                           lambda: f"warn when any row in the last {fmt_age(WINDOW)} has a device id not in "
                                   "MONITOR_DEVICES.",
                           "Look at the rows in Supabase; if they are not yours, the device-token insert policy "
                           "(roadmap) is the fix."),
    "weather/gaps": ("Are there missing hours in weather_hourly? The model needs outdoor conditions for every hour.",
                     lambda: f"warn when any hour of the last {fmt_age(WEATHER_GAP_WINDOW)} is missing.",
                     "Run `python3 jobs/fetch_weather.py --sync` (or start dashboard/serve.py, which does it)."),
    "weather/fresh": ("Has the weather sync run recently? It only runs while dashboard/serve.py runs.",
                      lambda: f"warn when the newest fetched_at is older than {fmt_age(WEATHER_STALE_AFTER)}.",
                      "Start dashboard/serve.py, or set up an always-on schedule (roadmap)."),
    "supabase": ("Can the monitor query Supabase at all? If not, every data check shows unknown instead of failing.",
                 lambda: "fail when any query fails (network, HTTP error, unexpected answer).",
                 "HTTP 401/403: key wrong or grants missing. Cannot connect: internet or SUPABASE_URL."),
    "http": ("Does a local service answer? Targets come from MONITOR_HTTP (dashboard now, API and proxy later).",
             lambda: "fail when the URL does not answer within 5 s or answers with HTTP 400 or above.",
             "Start the service, or remove it from MONITOR_HTTP."),
}


def explain(check_id):
    """(what it watches, rule with the current thresholds, what to do) for a check id, or None."""
    for key in (check_id, check_id.split("/")[-1], check_id.split("/")[0]):   # full id, node check, http/...
        if key in EXPLAIN:
            what, rule, todo = EXPLAIN[key]
            return what, rule(), todo
    return None
