"""Fetch hourly outdoor weather from Open-Meteo and upsert it into Supabase (table weather_hourly).

    python3 jobs/fetch_weather.py                  # last 2 days + 2 days of forecast
    python3 jobs/fetch_weather.py --past-days 17   # backfill (Open-Meteo allows up to 92)
    python3 jobs/fetch_weather.py --dry-run        # fetch and summarise, no database write
    python3 jobs/fetch_weather.py --sync           # find missing hours in weather_hourly, fill them, report

Settings come from the environment or the repository's .env file (see .env.example):
LATITUDE, LONGITUDE, SUPABASE_URL, SUPABASE_SECRET_KEY. Standard library only.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_PAST_DAYS = 92           # Open-Meteo's forecast API serves at most this many past days
FIRST_SYNC_DAYS = 30         # an empty table is filled this far back
REPO_ROOT = Path(__file__).resolve().parent.parent

# Open-Meteo hourly variable -> (weather_hourly column, unit the column expects)
VARIABLES = {
    "temperature_2m":       ("temp_c",          "°C"),
    "relative_humidity_2m": ("rh",              "%"),
    "dew_point_2m":         ("dew_point_c",     "°C"),
    "surface_pressure":     ("press_hpa",       "hPa"),
    "precipitation":        ("precip_mm",       "mm"),
    "cloud_cover":          ("cloud_cover_pct", "%"),
    "wind_speed_10m":       ("wind_speed_ms",   "m/s"),
    "wind_direction_10m":   ("wind_dir_deg",    "°"),
    "shortwave_radiation":  ("shortwave_wm2",   "W/m²"),
    "weather_code":         ("weather_code",    "wmo code"),
    "is_day":               ("is_day",          ""),
}


def load_env(path):
    """Read KEY=VALUE lines into os.environ without overriding variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch(lat, lon, past_days, forecast_days):
    params = {
        # Rounded to 2 decimals (about 1 km): finer than the weather model grid, so nothing is lost
        "latitude": f"{lat:.2f}",
        "longitude": f"{lon:.2f}",
        "hourly": ",".join(VARIABLES),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def to_rows(data, fetched_at):
    """Turn an Open-Meteo response into weather_hourly rows. Fails if a unit is not the one the column expects."""
    units = data["hourly_units"]
    for var, (col, unit) in VARIABLES.items():
        if unit and units.get(var) != unit:
            raise ValueError(f"{var}: expected unit {unit!r}, got {units.get(var)!r}")

    hourly = data["hourly"]
    rows = []
    for i, t in enumerate(hourly["time"]):
        observed_at = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        row = {"observed_at": observed_at.isoformat(), "source": "open-meteo", "fetched_at": fetched_at.isoformat()}
        for var, (col, _) in VARIABLES.items():
            value = hourly[var][i]
            if value is not None and col == "is_day":
                value = bool(value)
            elif value is not None and col == "weather_code":
                value = int(value)
            row[col] = value
        rows.append(row)
    return rows


def upsert(rows, supabase_url, key):
    url = f"{supabase_url.rstrip('/')}/rest/v1/weather_hourly?on_conflict=source,observed_at"
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    if key.startswith("eyJ"):   # legacy service_role JWT
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(rows).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def stored_hours(supabase_url, key, since):
    """observed_at of every open-meteo row in weather_hourly from `since` on, as a set of UTC datetimes."""
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    hours, offset, page = set(), 0, 1000
    while True:
        query = urllib.parse.urlencode({"select": "observed_at", "source": "eq.open-meteo",
                                        "observed_at": f"gte.{since.isoformat()}", "order": "observed_at",
                                        "limit": page, "offset": offset})
        req = urllib.request.Request(f"{supabase_url.rstrip('/')}/rest/v1/weather_hourly?{query}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.load(resp)
        hours.update(datetime.fromisoformat(r["observed_at"]).astimezone(timezone.utc) for r in rows)
        if len(rows) < page:
            return hours
        offset += page


def missing_hours(stored, start, end):
    """Whole UTC hours from start to end (both included) that are not in `stored`, oldest first."""
    t = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while t <= end:
        if t not in stored:
            out.append(t)
        t += timedelta(hours=1)
    return out


def sync(env=os.environ, now=None, log=print, fetch_fn=fetch, upsert_fn=upsert, stored_fn=stored_hours):
    """Check weather_hourly for missing hours since the first stored row (at most MAX_PAST_DAYS back), fetch enough
    past days to fill them plus the forecast, upsert, check again. Returns the hours still missing afterwards."""
    for name in ("LATITUDE", "LONGITUDE", "SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        if not env.get(name, "").strip():   # unset, or empty (GitHub Actions passes a missing secret as "")
            raise KeyError(name)
    lat, lon = float(env["LATITUDE"]), float(env["LONGITUDE"])
    url, key = env["SUPABASE_URL"], env["SUPABASE_SECRET_KEY"]
    now = now or datetime.now(timezone.utc)
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    oldest_fetchable = this_hour - timedelta(days=MAX_PAST_DAYS - 1)

    stored = stored_fn(url, key, oldest_fetchable)
    start = min(stored) if stored else this_hour - timedelta(days=FIRST_SYNC_DAYS)
    gaps = missing_hours(stored, start, this_hour)
    # Days back to the oldest gap (whole days, plus one so the gap's own day is included); 2 keeps recent hours fresh
    past_days = 2 if not gaps else min(MAX_PAST_DAYS, (this_hour - gaps[0]).days + 2)
    log(f"weather: {len(stored)} hours stored since {start:%Y-%m-%d}, {len(gaps)} missing; fetching {past_days} past days")

    rows = to_rows(fetch_fn(lat, lon, past_days, 2), now)
    upsert_fn(rows, url, key)
    left = missing_hours(stored_fn(url, key, oldest_fetchable), start, this_hour)
    if left:
        log(f"weather: still {len(left)} hours missing, first {left[0]:%Y-%m-%d %H:00} UTC")
    else:
        log(f"weather: complete from {start:%Y-%m-%d %H:00} to {this_hour:%Y-%m-%d %H:00} UTC, forecast "
            f"to {rows[-1]['observed_at'][:16]}")
    return left


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--past-days", type=int, default=2)
    parser.add_argument("--forecast-days", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="fetch and summarise, do not write")
    parser.add_argument("--sync", action="store_true", help="fill every missing hour, then report the coverage")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    if args.sync:
        try:
            sys.exit(1 if sync() else 0)
        except KeyError as e:
            sys.exit(f"Set {e.args[0]} in .env or the environment")
    try:
        lat, lon = float(os.environ["LATITUDE"]), float(os.environ["LONGITUDE"])
    except (KeyError, ValueError):
        sys.exit("Set LATITUDE and LONGITUDE (decimal degrees) in .env")

    fetched_at = datetime.now(timezone.utc)
    rows = to_rows(fetch(lat, lon, args.past_days, args.forecast_days), fetched_at)
    now_row = max((r for r in rows if r["observed_at"] <= fetched_at.isoformat()), key=lambda r: r["observed_at"])
    print(f"{len(rows)} hours, {rows[0]['observed_at']} .. {rows[-1]['observed_at']}")
    print(f"this hour: {now_row['temp_c']} °C, {now_row['rh']} %RH, dew point {now_row['dew_point_c']} °C, "
          f"{now_row['press_hpa']} hPa, code {now_row['weather_code']}")

    if args.dry_run:
        return
    try:
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    except KeyError:
        sys.exit("Set SUPABASE_URL and SUPABASE_SECRET_KEY in .env (or use --dry-run)")
    try:
        status = upsert(rows, url, key)
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase rejected the upsert: HTTP {e.code}: {e.read().decode(errors='replace')}")
    print(f"upserted into weather_hourly: HTTP {status}")


if __name__ == "__main__":
    main()
