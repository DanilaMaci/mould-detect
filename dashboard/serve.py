"""Local web server for the dashboard that tells the browser not to cache anything, and keeps the weather table
complete while it runs.

    python3 serve.py                 # http://localhost:8000
    python3 serve.py 8080
    python3 serve.py --no-weather    # serve only

Plain `python3 -m http.server` lets browsers keep old copies of the JavaScript modules, so a normal reload can show
an outdated dashboard. At start-up, and then every hour, the weather sync (jobs/fetch_weather.py --sync) looks for
missing hours in weather_hourly, fills them from Open-Meteo and prints the coverage; it needs LATITUDE, LONGITUDE,
SUPABASE_URL and SUPABASE_SECRET_KEY in the repository's .env and is skipped with a note when they are missing.
Standard library only.
"""
import argparse
import contextlib
import functools
import http.server
import socket
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
WEATHER_EVERY_S = 3600
sys.path.insert(0, str(REPO_ROOT / "jobs"))


class DualStackServer(http.server.ThreadingHTTPServer):
    """Listens on IPv6 and IPv4 at once, so http://localhost works whichever one the browser tries first."""
    address_family = socket.AF_INET6

    def server_bind(self):
        with contextlib.suppress(Exception):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        return super().server_bind()


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def weather_loop(stop):
    """Sync the weather now and then every hour until `stop` is set. Errors are printed, never fatal."""
    import fetch_weather   # jobs/fetch_weather.py

    try:
        fetch_weather.load_env(REPO_ROOT / ".env")
    except OSError as e:
        print(f"weather: skipped, cannot read .env ({e.strerror})")
        return
    while not stop.is_set():
        try:
            fetch_weather.sync()
        except KeyError as e:
            print(f"weather: skipped, set {e.args[0]} in .env to keep weather_hourly filled")
            return
        except Exception as e:   # network down, Supabase error: report and try again next hour
            print(f"weather: sync failed ({type(e).__name__}: {e}), retrying in an hour")
        stop.wait(WEATHER_EVERY_S)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--no-weather", action="store_true", help="do not sync the weather table")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # log lines appear at once, also when redirected to a file

    handler = functools.partial(NoCacheHandler, directory=str(HERE))
    try:
        server = DualStackServer(("::", args.port), handler)
    except OSError as e:
        sys.exit(f"Port {args.port} is not available ({e.strerror}). Another server is probably still running: "
                 f"stop it with `lsof -ti :{args.port} | xargs kill`, or use `python3 serve.py {args.port + 1}`.")
    with server:
        print(f"Serving the dashboard on http://localhost:{args.port} (also http://127.0.0.1:{args.port}); "
              "no caching; Ctrl+C to stop. Every page load prints GET lines here.")
        stop = threading.Event()
        if not args.no_weather:
            threading.Thread(target=weather_loop, args=(stop,), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()


if __name__ == "__main__":
    main()
