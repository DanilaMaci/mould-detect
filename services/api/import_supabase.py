"""Copy readings and weather from Supabase into the API's SQLite database, so the dashboard can run on the own API
with the real history. Read-only on Supabase; incremental (only rows newer than the newest one already copied).

    python3 services/api/import_supabase.py              # into data/api.sqlite
    python3 services/api/import_supabase.py --days 30    # first import: how far back (default 30)

Needs SUPABASE_URL and SUPABASE_SECRET_KEY in the repository's .env (the same as the weather job). The ESP32 keeps
posting to Supabase; run this again to catch up. Load tests must use their own database file (--db): their rows
would otherwise mix with the real ones and move the "newest row already copied" mark. Standard library only.
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

from db import COLUMNS, WEATHER_COLUMNS, Database, iso

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "jobs"))
from fetch_weather import load_env   # noqa: E402

PAGE = 1000   # Supabase's default maximum rows per answer


def rest_get(url, key, table, params):
    headers = {"apikey": key}
    if key.startswith("eyJ"):   # legacy service_role JWT
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{table}?{urllib.parse.urlencode(params)}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def pages(get, table, select, time_column, since, extra=()):
    """All rows with time_column > since, oldest first, a page at a time (keyset paging: each page starts after the
    last time seen, so rows inserted meanwhile cannot shift the pages)."""
    while True:
        rows = get(table, {"select": select, time_column: f"gt.{since}", "order": time_column, "limit": PAGE, **dict(extra)})
        yield rows
        if len(rows) < PAGE:
            return
        since = rows[-1][time_column]


def ts(value):
    return iso(datetime.fromisoformat(value))


def import_all(db, get, now, days=30, log=print):
    """Copy what is missing; returns (readings copied, weather hours copied)."""
    latest = db.latest("measured_at")
    since = (datetime.fromisoformat(latest.replace("Z", "+00:00")) if latest else now - timedelta(days=days)).isoformat()
    n_readings = 0
    for rows in pages(get, "indoor_readings", ",".join(COLUMNS), "measured_at", since):
        db.insert_many([{c: (ts(r[c]) if c in ("received_at", "measured_at") else r.get(c)) for c in COLUMNS}
                        for r in rows])
        n_readings += len(rows)
    # Weather: re-copy the last 3 days too, because the sync refines recent hours and the forecast changes
    latest_w = db.latest("observed_at")
    since_w = ((datetime.fromisoformat(latest_w.replace("Z", "+00:00")) - timedelta(days=3)) if latest_w
               else now - timedelta(days=days)).isoformat()
    n_weather = 0
    for rows in pages(get, "weather_hourly", ",".join(WEATHER_COLUMNS), "observed_at", since_w,
                      extra={"source": "eq.open-meteo"}):
        db.upsert_weather([{c: (ts(r[c]) if c in ("observed_at", "fetched_at") else r.get(c)) for c in WEATHER_COLUMNS}
                           for r in rows])
        n_weather += len(rows)
    log(f"copied {n_readings} readings (now {db.count()} stored) and {n_weather} weather hours")
    return n_readings, n_weather


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "api.sqlite")
    parser.add_argument("--days", type=int, default=30, help="how far back the first import goes")
    args = parser.parse_args()
    load_env(REPO_ROOT / ".env")
    try:
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"]
    except KeyError as e:
        sys.exit(f"Set {e.args[0]} in .env")
    args.db.parent.mkdir(exist_ok=True)
    try:
        import_all(Database(args.db), lambda table, params: rest_get(url, key, table, params),
                   datetime.now(timezone.utc), args.days)
    except urllib.error.HTTPError as e:
        sys.exit(f"Supabase answered HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach Supabase ({e.reason})")


if __name__ == "__main__":
    main()
