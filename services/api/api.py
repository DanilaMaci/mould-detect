"""Mini API for the sensor readings, standard library only: the hand-written twin of a FastAPI app, built to be read,
reviewed and load-tested.

    python3 services/api/api.py                      # http://127.0.0.1:8200, data in data/api.sqlite
    python3 services/api/api.py --max-in-flight 64   # shed load earlier
    python3 services/api/api.py --access-log         # one line per request (slows it down under load)

Endpoints:
    GET  /api/health          no token        {"status": "ok", "readings": n}
    POST /api/readings        device token    one reading, same JSON as the ESP32 sends to Supabase -> 201
    GET  /api/readings        read token      ?device_id=&since=&until=&limit=&hourly=1
    GET  /api/weather         read token      ?since=&until=&limit=
    GET  /metrics             no token        Prometheus text format
    GET  /traffic             no token        live traffic page (rate, errors, latency percentiles)

Tokens come from the environment or the repository's .env: API_DEVICE_TOKENS="node1=<token>,node2=<token>" (the
device id is taken from the token, so a node can only write as itself) and API_READ_TOKEN (dashboard, scripts).
Make one with: python3 -c 'import secrets; print(secrets.token_urlsafe(24))'. API_CORS_ORIGINS lists the web origins
allowed to call the API from a browser (default: the dashboard's serve.py on localhost/127.0.0.1:8000).
"""
import argparse
import hmac
import json
import os
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import validate
from db import Database
from metrics import Metrics

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "jobs"))
from fetch_weather import load_env   # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "api.sqlite"
MAX_BODY = 4096          # bytes; the firmware's JSON is under 400
MIN_TOKEN = 16           # characters; shorter tokens are refused at start-up
UNLIMITED = ("metrics", "traffic")   # monitoring routes are never shed
STATIC = {"/traffic": ("traffic.html", "text/html; charset=utf-8"),
          "/traffic.js": ("traffic.js", "text/javascript; charset=utf-8")}


class App:
    """Everything the request handlers share: settings, database, metrics, the in-flight limit."""

    def __init__(self, db, device_tokens, read_token, cors_origins=("http://localhost:8000", "http://127.0.0.1:8000"), max_in_flight=400,
                 access_log=False, clock=lambda: datetime.now(timezone.utc)):
        self.db, self.device_tokens, self.read_token = db, dict(device_tokens), read_token
        self.cors_origins, self.access_log, self.clock = set(cors_origins), access_log, clock
        self.metrics = Metrics()
        self.slots = threading.BoundedSemaphore(max_in_flight)

    def device_for(self, token):
        """Device id whose token this is, or None. Every token is compared (constant time each) so the answer
        time does not tell which one nearly matched."""
        found = None
        for device, expected in self.device_tokens.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                found = device
        return found

    def can_read(self, token):
        return bool(self.read_token) and hmac.compare_digest(token.encode(), self.read_token.encode())


def route_name(method, path):
    """Fixed route names for metrics labels and dispatch; anything else is 'other'."""
    if path == "/api/readings":
        return {"POST": "post_reading", "GET": "get_readings", "OPTIONS": "preflight"}.get(method, "other")
    if path in ("/api/health", "/api/weather"):
        return {"GET": path[5:], "OPTIONS": "preflight"}.get(method, "other")
    if method == "GET" and path == "/metrics":
        return "metrics"
    if method == "GET" and path in (*STATIC, "/traffic.json"):
        return "traffic"
    return "other"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive: load generators (and browsers) reuse connections
    timeout = 10                    # an idle or slow client cannot hold a thread for ever
    app: App = None                 # set by make_server

    def setup(self):                # once per TCP connection, before its first request
        super().setup()
        self.app.metrics.connected()

    def version_string(self):       # default would advertise the exact Python version
        return "mould-api"

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_OPTIONS(self):
        self.dispatch("OPTIONS")

    def dispatch(self, method):
        started = time.perf_counter()
        url = urllib.parse.urlsplit(self.path)
        route = route_name(method, url.path)
        app = self.app
        app.metrics.started()
        status = 500
        try:
            if route in UNLIMITED:   # cheap, and needed most exactly when the server is overloaded
                status = getattr(self, "r_" + route)(url)
                return
            if not app.slots.acquire(blocking=False):
                # Load shedding: answering 503 at once is cheaper than queueing until every client times out. The
                # small body is read and dropped so the connection stays usable: closing it would make the client
                # reconnect at once (new connection, new thread), adding load exactly when there is too much.
                app.metrics.shed_one()
                status = self.send_json(503, {"error": "busy, retry later"}, close=not self.drain_body(),
                                        headers={"Retry-After": "1"})
                return
            try:
                status = getattr(self, "r_" + route)(url)
            finally:
                app.slots.release()
        except sqlite3.OperationalError:   # the database stayed locked longer than db.BUSY_TIMEOUT
            status = self.send_json(503, {"error": "database busy, retry later"}, headers={"Retry-After": "1"})
        except (ConnectionError, TimeoutError):
            # The client went away (or stalled) mid-request: nothing to answer. Counted as 499, nginx's code for
            # "client closed request", so that 500 only ever means a bug in this server.
            self.close_connection = True
            status = 499
        except Exception:
            traceback.print_exc()
            status = self.send_json(500, {"error": "internal error"}, close=True)
        finally:
            app.metrics.finished(route, method, status, time.perf_counter() - started, live=route != "traffic")

    # --- routes ---------------------------------------------------------------------------------------------------

    def r_health(self, url):
        return self.send_json(200, {"status": "ok", "readings": self.app.db.count()})

    def r_post_reading(self, url):
        device = self.app.device_for(self.bearer())
        if device is None:
            return self.send_json(401, {"error": "missing or unknown device token"}, close=True)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.send_json(415, {"error": "Content-Type must be application/json"}, close=True)
        body, status = self.read_body()
        if body is None:
            return status
        try:
            data = validate.parse_json(body)
        except (ValueError, UnicodeDecodeError) as e:
            return self.send_json(400, {"error": f"invalid JSON: {e}"[:200]})
        now = self.app.clock()
        row, problems = validate.reading(data, device, now)
        if problems:
            return self.send_json(422, {"error": "invalid reading", "problems": problems})
        row_id = self.app.db.insert_reading(row, now)
        return self.send_json(201, {"id": row_id})

    def r_get_readings(self, url):
        q, status = self.read_query(url)
        if q is None:
            return status
        db = self.app.db
        rows = (db.readings_hourly if q["hourly"] else db.readings)(q["device_id"], q["since"], q["until"], q["limit"])
        return self.send_json(200, rows)

    def r_weather(self, url):
        q, status = self.read_query(url)
        if q is None:
            return status
        return self.send_json(200, self.app.db.weather(q["since"], q["until"], q["limit"]))

    def r_metrics(self, url):
        db = self.app.db
        text = self.app.metrics.prometheus(extra=[
            ("api_readings_stored", "gauge", "Rows in the readings table.", db.count()),
            ("api_db_bytes", "gauge", "Size of the SQLite file (without the WAL file).", Path(db.path).stat().st_size)])
        return self.send(200, text.encode(), "text/plain; version=0.0.4; charset=utf-8")

    def r_traffic(self, url):
        if url.path == "/traffic.json":
            return self.send_json(200, self.app.metrics.window())
        name, ctype = STATIC[url.path]
        return self.send(200, (HERE / "static" / name).read_bytes(), ctype)

    def r_preflight(self, url):
        # CORS preflight: the browser asks before a cross-origin request with an Authorization header
        return self.send(204, b"", None)

    def r_other(self, url):
        return self.send_json(404 if self.command in ("GET", "POST", "OPTIONS") else 405, {"error": "not found"},
                              close=self.command == "POST")

    # --- helpers --------------------------------------------------------------------------------------------------

    def bearer(self):
        auth = self.headers.get("Authorization", "")
        return auth[7:].strip() if auth.startswith("Bearer ") else ""

    def read_query(self, url):
        if not self.app.can_read(self.bearer()):
            return None, self.send_json(401, {"error": "missing or wrong read token"})
        q, problems = validate.query(urllib.parse.parse_qs(url.query), self.app.clock())
        if problems:
            return None, self.send_json(422, {"error": "invalid query", "problems": problems})
        return q, None

    def read_body(self):
        """(bytes, None) or (None, status already sent). Without a valid Content-Length the connection is closed,
        because the server cannot tell where this request ends and the next one starts."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return None, self.send_json(411, {"error": "send Content-Length, not chunked"}, close=True)
        try:
            length = int(self.headers["Content-Length"])
        except (TypeError, ValueError):
            return None, self.send_json(411, {"error": "Content-Length required"}, close=True)
        if not 0 <= length <= MAX_BODY:
            return None, self.send_json(413, {"error": f"body over {MAX_BODY} bytes"}, close=True)
        return self.rfile.read(length), None

    def drain_body(self):
        """Read and drop the request body if it is small and properly framed; False when the connection must close."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return False
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return False
        if not 0 <= length <= MAX_BODY:
            return False
        self.rfile.read(length)
        return True

    def send_json(self, status, payload, close=False, headers=None):
        return self.send(status, json.dumps(payload, separators=(",", ":")).encode(), "application/json", close, headers)

    def send(self, status, body, ctype, close=False, headers=None):
        self.send_response(status)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if ctype and ctype.startswith("text/html"):
            # the traffic page: its own script and data only, no framing
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; connect-src 'self'; "
                                                        "style-src 'unsafe-inline'; frame-ancestors 'none'")
        origin = self.headers.get("Origin")
        if origin in self.app.cors_origins:   # only listed sites may read answers from a browser
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            if self.command == "OPTIONS":
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return status

    def log_message(self, fmt, *args):
        if self.app.access_log:
            super().log_message(fmt, *args)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128   # listen backlog: connections waiting for accept(); the default 5 refuses bursts

    def handle_error(self, request, client_address):
        """A client resetting an idle keep-alive connection is normal (load tests end that way); anything else is
        printed with its traceback."""
        if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            super().handle_error(request, client_address)


def make_server(app, host="127.0.0.1", port=8200):
    handler = type("BoundHandler", (Handler,), {"app": app})
    return Server((host, port), handler)


def tokens_from_env(env=os.environ):
    """(device tokens dict, read token); ValueError for malformed or weak settings."""
    devices = {}
    for item in filter(None, (s.strip() for s in env.get("API_DEVICE_TOKENS", "").split(","))):
        device, sep, token = item.partition("=")
        if not sep or not 0 < len(device) <= 32 or len(token) < MIN_TOKEN:
            raise ValueError(f"API_DEVICE_TOKENS: expected device=token with tokens of {MIN_TOKEN}+ characters")
        devices[device] = token
    read = env.get("API_READ_TOKEN", "").strip()
    if read and len(read) < MIN_TOKEN:
        raise ValueError(f"API_READ_TOKEN: use {MIN_TOKEN}+ characters")
    if read and read in devices.values():
        raise ValueError("API_READ_TOKEN must differ from every device token")
    return devices, read


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this Mac only)")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    # 400: measured on the 8-core Mac (loadtest, 2026-10-26): peaks reach ~350 at 2000 req/s while still fast, 650 in
    # the meltdown just above. A limit from averages (Little's law: ~15) would refuse work the server can do.
    parser.add_argument("--max-in-flight", type=int, default=400, help="requests handled at once; more get 503")
    parser.add_argument("--access-log", action="store_true", help="print one line per request")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    try:
        load_env(REPO_ROOT / ".env")
    except OSError as e:
        print(f"cannot read .env ({e.strerror}); using the environment only")
    try:
        devices, read = tokens_from_env()
    except ValueError as e:
        sys.exit(str(e))
    origins = [o.strip() for o in os.environ.get("API_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if o.strip()]
    args.db.parent.mkdir(exist_ok=True)
    app = App(Database(args.db), devices, read, origins, args.max_in_flight, args.access_log)
    server = make_server(app, args.host, args.port)
    print(f"API on http://{args.host}:{args.port} (traffic page /traffic, metrics /metrics); "
          f"{len(devices)} device token(s), read token {'set' if read else 'NOT set (reads refused)'}; "
          f"max {args.max_in_flight} requests in flight; Ctrl+C to stop")
    if not devices:
        print("No API_DEVICE_TOKENS: every POST is refused (fail closed)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
