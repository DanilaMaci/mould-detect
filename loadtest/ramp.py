"""Load test for services/api: starts a throwaway copy of the API (own port, own database, random tokens), seeds it
with a day of readings, runs Locust, saves everything in a new folder and prints the result.

    .venv/bin/python loadtest/ramp.py                        # ramp until it breaks (headless, a few minutes)
    .venv/bin/python loadtest/ramp.py --max-in-flight 256    # same, with a different API setting to compare
    .venv/bin/python loadtest/ramp.py --processes 4          # 4 load-generator processes (if Locust is the limit)
    .venv/bin/python loadtest/ramp.py --ui                   # Locust's web page on http://127.0.0.1:8089: you
                                                             # choose users and watch; Ctrl+C ends it

Results: data/loadtests/<date>_<time>_<label>/ — ramp.json (one row per step and the verdict), locust_*.csv,
report.html (Locust's charts), api.log, api_metrics.txt (the API's /metrics at the end), run.json (settings).
Never touches data/api.sqlite or Supabase. Ramp size: RAMP_STEP_USERS (50), RAMP_STEP_SECONDS (10),
RAMP_MAX_USERS (3000) in the environment.
"""
import argparse
import json
import os
import platform
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
from db import Database, iso   # noqa: E402

LOCUST = REPO_ROOT / ".venv" / "bin" / "locust"


def seed(db, now):
    """A day of minute readings for node1 (what a dashboard viewer loads) and 3 days of weather."""
    rows = []
    for m in range(24 * 60, 0, -1):
        t = iso(now - timedelta(minutes=m))
        rows.append({"device_id": "node1", "received_at": t, "measured_at": t, "temp_c": 21.0 + (m % 30) / 10,
                     "rh": 55.0, "press_hpa": 1003.0, "rssi_dbm": -60, "co2_ppm": 600 + m % 400, "scd_temp_c": 21.5,
                     "scd_rh": 53.0, "wall_temp_c": 17.0, "outdoor_temp_c": None, "window_open": False,
                     "door_open": True})
    db.insert_many(rows)
    hour = now.replace(minute=0, second=0, microsecond=0)
    db.upsert_weather([{"observed_at": iso(hour - timedelta(hours=h)), "temp_c": 9.0, "rh": 85.0, "dew_point_c": 6.6,
                        "press_hpa": 1003.0, "precip_mm": 0.0, "cloud_cover_pct": 80.0, "wind_speed_ms": 4.0,
                        "wind_dir_deg": 230.0, "shortwave_wm2": 0.0, "weather_code": 3, "is_day": 0,
                        "fetched_at": iso(now)} for h in range(-48, 72)])


def wait_for(url, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ui", action="store_true", help="Locust web page instead of the automatic ramp")
    parser.add_argument("--port", type=int, default=8201, help="port for the throwaway API (default 8201)")
    parser.add_argument("--max-in-flight", type=int, default=400, help="passed to the API (its default is 400)")
    parser.add_argument("--processes", type=int, default=4,
                        help="Locust processes generating load (default 4: one process holds at most ~1000 connections)")
    parser.add_argument("--label", default="api", help="name part of the results folder")
    args = parser.parse_args()
    if not LOCUST.exists():
        sys.exit("Locust not found: python3 -m venv .venv && .venv/bin/python -m pip install locust")

    now = datetime.now(timezone.utc)
    out = REPO_ROOT / "data" / "loadtests" / f"{now.astimezone():%Y-%m-%d_%H%M%S}_{args.label}"
    out.mkdir(parents=True)
    device_token, read_token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    seed(Database(out / "api.sqlite"), now)
    (out / "run.json").write_text(json.dumps({
        "started": now.isoformat(), "mode": "ui" if args.ui else "ramp", "max_in_flight": args.max_in_flight,
        "locust_processes": args.processes, "sync": os.environ.get("LOADTEST_SYNC") == "1", "cpus": os.cpu_count(), "machine": platform.machine(),
        "python": platform.python_version(), "ramp": {k: os.environ.get(k) for k in
                                                       ("RAMP_STEP_USERS", "RAMP_STEP_SECONDS", "RAMP_MAX_USERS")},
    }, indent=1))

    base = f"http://127.0.0.1:{args.port}"
    api_env = {**os.environ, "API_DEVICE_TOKENS": f"loadtest={device_token}", "API_READ_TOKEN": read_token}
    with open(out / "api.log", "w") as log:
        api = subprocess.Popen([sys.executable, str(REPO_ROOT / "services" / "api" / "api.py"), "--port", str(args.port),
                                "--db", str(out / "api.sqlite"), "--max-in-flight", str(args.max_in_flight)],
                               env=api_env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait_for(f"{base}/api/health"):
            sys.exit(f"the API did not start; see {out / 'api.log'}")
        print(f"Throwaway API on {base} (live traffic: {base}/traffic); results in {out.relative_to(REPO_ROOT)}")
        locust_env = {**os.environ, "LOADTEST_DEVICE_TOKEN": device_token, "LOADTEST_READ_TOKEN": read_token,
                      "RAMP_OUT": str(out / "ramp.json")}
        cmd = [str(LOCUST), "--host", base, "--csv", str(out / "locust"), "--html", str(out / "report.html"),
               "--web-host", "127.0.0.1", "--loglevel", "WARNING"]   # Locust's page otherwise listens on all networks
        if args.processes > 1:
            cmd += ["--processes", str(args.processes)]
        if args.ui:
            cmd += ["-f", str(HERE / "locustfile.py")]
            print("Locust's page: http://127.0.0.1:8089 — set users and spawn rate, press Start; Ctrl+C here ends it")
        else:
            cmd += ["-f", f"{HERE / 'locustfile.py'},{HERE / 'ramp_shape.py'}", "--headless", "--only-summary"]
            print("Ramping: +{} users every {} s until it breaks...".format(os.environ.get("RAMP_STEP_USERS", 50),
                                                                          os.environ.get("RAMP_STEP_SECONDS", 10)))
        try:
            subprocess.run(cmd, env=locust_env, cwd=REPO_ROOT)
        except KeyboardInterrupt:
            pass
        for attempt in range(5):   # the API may still be busy with the last users' connections
            try:
                with urllib.request.urlopen(f"{base}/metrics", timeout=5) as resp:
                    (out / "api_metrics.txt").write_bytes(resp.read())
                break
            except OSError as e:
                if attempt == 4:
                    print(f"could not save the API's metrics ({e})")
                time.sleep(2)
    finally:
        api.terminate()
        api.wait(10)

    ramp = out / "ramp.json"
    if ramp.exists():
        result = json.loads(ramp.read_text())
        print(f"\n{'users':>6} {'offered':>8} {'req/s':>8} {'fail %':>7} {'p50 ms':>7} {'p95 ms':>7} {'p99 ms':>7} "
              f"{'server p99':>10} {'peak':>5} {'shed':>7} {'conns':>7} {'locust cpu':>10}")
        for s in result["steps"]:
            print(f"{s['users']:>6} {s['target_rps']:>8} {s['rps']:>8} {s['fail_pct']:>7} {s['p50_ms']!s:>7} "
                  f"{s['p95_ms']!s:>7} {s['p99_ms']!s:>7} {s.get('server_p99_ms', '-')!s:>10} "
                  f"{s.get('server_in_flight_peak', '-')!s:>5} {s.get('server_shed_total', '-')!s:>7} {s.get('server_connections_total', '-')!s:>7} {s['locust_cpu_pct']:>9}%")
        print(f"\n{result['verdict']}")
    print(f"Files: {out.relative_to(REPO_ROOT)}/ (report.html has Locust's charts)")


if __name__ == "__main__":
    main()
