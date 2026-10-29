"""End-to-end tests of the monitor against a fake Supabase REST API and a fake ntfy, plus the status page on a real
local port. Run: python3 -m unittest discover -s services/monitor"""
import json
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import monitor
from checks import FAIL, OFF, OK
import store as store_module
from store import Store

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)
KEY = "test-secret-key-do-not-leak"
ENV = {"SUPABASE_URL": "https://example.invalid/", "SUPABASE_SECRET_KEY": KEY, "NTFY_TOPIC": "test_topic_0123456789"}


class FakeSupabase:
    """Answers the PostgREST queries the monitor makes: eq./not.in./gte./not.is.null filters, order, limit, select,
    and like Supabase never returns more than MAX_ROWS rows per answer."""
    MAX_ROWS = 1000

    def __init__(self):
        self.tables = {"indoor_readings": [], "weather_hourly": []}
        self.error = None
        self.queries = []

    def get(self, cfg, table, params):
        self.queries.append((table, dict(params)))
        if self.error:
            raise self.error
        rows = self.tables[table]
        for col, cond in params.items():
            if col in ("select", "order", "limit"):
                continue
            if cond == "not.is.null":
                rows = [r for r in rows if r.get(col) is not None]
            elif cond.startswith("not.in.(") and cond.endswith(")"):
                rows = [r for r in rows if str(r.get(col)) not in cond[8:-1].split(",")]
            elif cond.startswith("eq."):
                rows = [r for r in rows if str(r.get(col)) == cond[3:]]
            elif cond.startswith("gte."):
                rows = [r for r in rows if datetime.fromisoformat(r[col]) >= datetime.fromisoformat(cond[4:])]
            else:
                raise AssertionError(f"filter not faked: {col}={cond}")
        col, _, desc = params["order"].partition(".")
        rows = sorted(rows, key=lambda r: datetime.fromisoformat(r[col]), reverse=desc == "desc")
        cols = params["select"].split(",")
        return [{c: r.get(c) for c in cols} for r in rows[:min(int(params["limit"]), self.MAX_ROWS)]]

    def add_reading(self, t, device="node1", **values):
        row = {"device_id": device, "measured_at": t.isoformat(), "received_at": t.isoformat(), "temp_c": 21.0,
               "rh": 50.0 + (t.minute % 5) * 0.1, "press_hpa": 1000.0 + (t.minute % 3) * 0.1,
               "co2_ppm": 700 + t.minute % 9, "scd_temp_c": 21.5 + (t.minute % 4) * 0.1, "scd_rh": 48.0 + (t.minute % 6) * 0.1,
               "wall_temp_c": 17.0 + (t.minute % 2) * 0.0625, "outdoor_temp_c": None}
        row["temp_c"] += (t.minute % 7) * 0.01
        row.update(values)
        self.tables["indoor_readings"].append(row)

    def fill(self, start, end, **values):
        t = start
        while t <= end:
            self.add_reading(t, **values)
            t += MIN

    def add_weather(self, hours_back, fetched_at):
        for h in range(-48, hours_back):
            t = NOW - timedelta(hours=h)
            self.tables["weather_hourly"].append({"observed_at": t.isoformat(), "source": "open-meteo",
                                                  "fetched_at": fetched_at.isoformat()})


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Path(self.dir.name) / "monitor.sqlite"
        self.store = Store(self.db)
        self.cfg = monitor.config(ENV)
        self.fake = FakeSupabase()
        self.fake.fill(NOW - 200 * MIN, NOW - MIN)
        self.fake.add_weather(80, NOW - 20 * MIN)
        self.sent = []
        self.log = []

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def send(self, cfg, title, message, priority, tags):
        self.sent.append((title, priority))

    def run_at(self, minutes, send=None):
        return monitor.run_once(self.cfg, self.store, NOW + minutes * MIN, get=self.fake.get,
                                send=send or self.send, log=self.log.append)

    def test_node_goes_silent_and_comes_back(self):
        for m in range(0, 18):   # last row at NOW - 1 min; nothing arrives afterwards
            self.run_at(m)
        self.fake.fill(NOW + 18 * MIN, NOW + 18 * MIN)
        self.run_at(18)
        self.run_at(19)
        # Exactly three alerts: the sensor checks of the silent node went unknown and never alerted
        self.assertEqual(self.sent, [("WARN node1/silent", "default"), ("FAIL node1/silent", "high"),
                                     ("OK node1/silent (was fail)", "low")])
        status = {r["check_id"]: r["status"] for r in self.store.checks()}
        self.assertEqual(status["node1/silent"], OK)
        self.assertEqual(status["node1/outdoor_probe"], OFF)   # never fitted: off, not an alert

    def test_probe_lookback_finds_a_lost_wall_probe(self):
        # wall probe reported until 5 h ago (outside the 3 h window): lost, not "never fitted"
        self.fake.tables["indoor_readings"].clear()
        self.fake.fill(NOW - 400 * MIN, NOW - 300 * MIN)
        self.fake.fill(NOW - 299 * MIN, NOW - MIN, wall_temp_c=None)
        results = {r.check: r for r in self.run_at(0)}
        self.assertEqual(results["node1/wall_probe"].status, FAIL)
        self.assertIn("5.0 h", results["node1/wall_probe"].message)
        self.assertEqual(results["node1/outdoor_probe"].status, OFF)
        lookups = [p for t, p in self.fake.queries if p.get("wall_temp_c") == "not.is.null"]
        self.assertEqual(len(lookups), 1)

    def test_alert_waits_in_the_outbox_while_ntfy_is_down(self):
        def down(*args):
            raise urllib.error.URLError("network unreachable")
        self.fake.add_reading(NOW - MIN / 2, wall_temp_c=85.0)
        self.run_at(0, send=down)
        self.run_at(1, send=down)   # ranges fail committed here, delivery fails
        self.assertEqual(self.sent, [])
        self.assertTrue(any("not delivered" in line for line in self.log))
        self.run_at(2)
        self.assertEqual(self.sent, [("FAIL node1/ranges", "high")])

    def test_flaky_ntfy_keeps_alert_order(self):
        calls = []

        def first_call_fails(cfg, title, *args):
            calls.append(title)
            if len(calls) == 1:
                raise urllib.error.URLError("timed out")
            self.sent.append(title)
        self.fake.add_reading(NOW - MIN / 2, wall_temp_c=85.0)
        self.fake.add_reading(NOW - MIN / 2, device="node9")
        self.run_at(0, send=first_call_fails)
        self.run_at(1, send=first_call_fails)   # two alerts queued; the first send fails
        self.run_at(2, send=first_call_fails)
        self.assertEqual(self.sent, ["FAIL node1/ranges", "WARN devices/unexpected"])

    def test_supabase_error_text_never_contains_the_key(self):
        self.run_at(0)
        self.run_at(1)
        self.fake.error = urllib.error.HTTPError(f"https://example.invalid/rest/v1/x?apikey={KEY}", 401,
                                                 "Unauthorized", {}, None)
        self.run_at(2)
        self.run_at(3)
        self.assertEqual(self.sent, [("FAIL supabase", "high")])   # data checks went unknown: no storm
        dump = json.dumps(monitor.status_data(self.store, 60, NOW + 3 * MIN))
        self.assertIn("HTTP 401 Unauthorized", dump)
        self.assertNotIn(KEY, dump)

    def test_flood_of_other_rows_does_not_hide_the_newest_node_row(self):
        # someone with the public key inserts 3000 rows; Supabase answers at most 1000 rows per query
        for i in range(3000):
            self.fake.add_reading(NOW - MIN + i * timedelta(milliseconds=10), device="spam")
        for i in range(1200):   # also a burst under the node's own id: more rows than one answer holds
            self.fake.add_reading(NOW - 20 * MIN + i * timedelta(milliseconds=500))
        self.fake.add_reading(NOW - MIN / 3, wall_temp_c=85.0)   # the newest node1 row is the broken one
        results = {r.check: r for r in self.run_at(0)}
        self.assertEqual(results["node1/ranges"].status, FAIL)
        self.assertEqual(results["node1/silent"].status, OK)
        self.assertIn("1 unexpected device id(s)", results["devices/unexpected"].message)

    def test_alert_raised_while_muted_is_never_sent(self):
        def down(*args):
            raise urllib.error.URLError("network unreachable")
        self.fake.add_reading(NOW - MIN / 2, device="node9")
        self.run_at(0, send=down)
        self.run_at(1, send=down)   # devices/unexpected alert stuck in the outbox, ahead of what follows
        self.store.mute("node1/ranges", NOW + 5 * MIN)
        self.fake.add_reading(NOW + MIN, wall_temp_c=85.0)
        self.run_at(2, send=down)
        self.run_at(3, send=down)   # ranges fail committed during the mute, queued behind the stuck alert
        self.run_at(10)             # mute over, ntfy back: only the unmuted alert goes out
        self.assertEqual(self.sent, [("WARN devices/unexpected", "default")])
        self.assertEqual(self.store.transitions(1)[0]["delivery"], "muted")

    def test_rejected_alert_does_not_block_the_rest(self):
        def reject_ranges(cfg, title, *args):
            if "ranges" in title:
                raise urllib.error.HTTPError("https://ntfy.invalid/x", 400, "Bad Request", {}, None)
            self.sent.append(title)
        self.fake.add_reading(NOW - MIN / 2, wall_temp_c=85.0)
        self.fake.add_reading(NOW - MIN / 2, device="node9")
        self.run_at(0, send=reject_ranges)
        self.run_at(1, send=reject_ranges)
        self.assertEqual(self.sent, ["WARN devices/unexpected"])
        delivery = {t["check_id"]: t["delivery"] for t in self.store.transitions() if t["alert"]}
        self.assertEqual(delivery["node1/ranges"], "failed")

    def test_no_topic_means_no_sending(self):
        self.cfg = monitor.config({**ENV, "NTFY_TOPIC": ""})
        self.fake.add_reading(NOW - MIN / 2, rh=100.0)
        self.run_at(0)
        self.run_at(1)
        self.assertEqual(self.sent, [])
        self.assertTrue(any("node1/ranges: unknown -> fail" in line for line in self.log))


class ConfigTest(unittest.TestCase):
    def test_defaults_and_targets(self):
        cfg = monitor.config({**ENV, "MONITOR_HTTP": "dashboard=http://localhost:8000/, api=http://127.0.0.1:8200/health"})
        self.assertEqual(cfg["devices"], ["node1"])
        self.assertEqual(cfg["ntfy_server"], "https://ntfy.sh")
        self.assertEqual(cfg["http"], {"dashboard": "http://localhost:8000/", "api": "http://127.0.0.1:8200/health"})
        self.assertEqual(cfg["supabase_url"], "https://example.invalid")

    def test_rejects_bad_values(self):
        for bad in ({"NTFY_TOPIC": "a/b"}, {"NTFY_TOPIC": "x\r\nInjected: 1"}, {"MONITOR_HTTP": "dash=file:///etc/passwd"},
                    {"MONITOR_HTTP": "no-equals-sign"}):
            with self.assertRaises(ValueError, msg=bad):
                monitor.config({**ENV, **bad})
        for bad in ({"SUPABASE_URL": "abc.supabase.co"}, {"NTFY_SERVER": "ntfy.sh"},
                    {"MONITOR_DEVICES": "node1,nöde2"}, {"MONITOR_DEVICES": "node1,a b"}):
            with self.assertRaises(ValueError, msg=bad):
                monitor.config({**ENV, **bad})
        with self.assertRaises(KeyError):
            monitor.config({"SUPABASE_URL": "https://example.invalid"})

    def test_error_text_hides_urls(self):
        # urllib puts the whole URL, topic included, into some messages
        text = monitor.describe(ValueError("unknown url type: 'ntfy.sh/secret_topic_123'"))
        self.assertNotIn("secret_topic_123", text)
        self.assertEqual(text, "ValueError: unknown url type: <url>")

    def test_postgrest_timestamp_formats(self):
        for value in ("2026-10-26T12:00:00+00:00", "2026-10-26T12:00:00.12345+00:00", "2026-10-26T12:00:00Z",
                      "2026-10-26T14:00:00+02:00"):
            self.assertEqual(monitor.ts(value).replace(microsecond=0), NOW, value)

    def test_rest_get_sends_key_and_encodes_filters(self):
        seen = {}

        class Capture(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["path"], seen["apikey"] = self.path, self.headers["apikey"]
                body = b"[]"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cfg = monitor.config({**ENV, "SUPABASE_URL": f"http://127.0.0.1:{server.server_port}"})
            monitor.rest_get(cfg, "indoor_readings", {"measured_at": f"gte.{NOW.isoformat()}", "limit": 1})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen["apikey"], KEY)
        self.assertIn("measured_at=gte.2026-10-26T12%3A00%3A00%2B00%3A00", seen["path"])   # + must not become a space


class StatusPageTest(unittest.TestCase):
    """The page and its buttons over real HTTP on a free local port."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Path(self.dir.name) / "monitor.sqlite"
        self.sent = []
        self.controls = monitor.Controls(monitor.config(ENV), 60, self.db, send=self.send, run_wait=0.5)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), monitor.make_handler(self.controls))
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def send(self, cfg, title, *args):
        self.sent.append(title)

    def fetch(self, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:   # follows the 303 after a button
                return resp.status, resp.headers, resp.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers, e.read().decode()

    def press(self, **form):
        """POST a button with the token from the page, as the browser would."""
        token = re.search(r"name='token' value='([^']+)'", self.fetch("/")[2]).group(1)
        return self.fetch("/action", urllib.parse.urlencode({"token": token, **form}).encode())

    def run_monitor(self, runs=2, unexpected=None, **values):
        fake = FakeSupabase()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fake.fill(now - 30 * MIN, now - MIN)
        fake.add_reading(now - MIN / 2, **values)
        if unexpected:
            fake.add_reading(now - MIN / 2, device=unexpected)
        store = Store(self.db)
        for m in range(runs):
            monitor.run_once(self.controls.cfg, store, now + m * MIN / 60, get=fake.get, send=self.send,
                             log=lambda *a: None)
        store.close()

    def test_page_escapes_explains_and_hides_secrets(self):
        code, _, body = self.fetch("/healthz")
        self.assertEqual((code, body), (503, "stale\n"))   # never ran
        self.run_monitor(unexpected="<script>alert(1)</script>")

        code, headers, body = self.fetch("/")
        self.assertEqual(code, 200)
        self.assertIn("devices/unexpected", body)
        self.assertNotIn("<script>alert", body)
        self.assertIn("?script?alert?1???script?", body)   # cleaned in checks.unexpected_devices
        self.assertIn("<b>Watches:</b> Is the node still sending?", body)   # explanation of node1/silent
        self.assertIn("warn when the newest row is 5 min old", body)
        csp = headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn(ENV["NTFY_TOPIC"], body)   # the topic is the secret on ntfy.sh
        self.assertNotIn(KEY, body)

        code, _, body = self.fetch("/status.json")
        data = json.loads(body)
        self.assertTrue(data["monitor_ok"])
        self.assertIn("node1/silent", {c["check_id"] for c in data["checks"]})
        self.assertNotIn(self.controls.token, body)
        self.assertEqual(self.fetch("/healthz")[:3:2], (200, "ok\n"))
        self.assertEqual(self.fetch("/../etc/passwd")[0], 404)

    def test_render_escapes_everything_from_the_database(self):
        # second line of defence behind the id cleaning: any stored text is escaped
        evil = "<script>alert(1)</script>"
        row = {"check_id": "node1/silent", "status": "fail", "message": evil, "since": NOW.isoformat(),
               "pending": None, "pending_runs": 0}
        trans = {"at": NOW.isoformat(), "check_id": evil, "old_status": "ok", "new_status": "fail", "message": evil,
                 "alert": 1, "delivery": None}
        page = monitor.render({"checks": [row], "transitions": [trans], "mutes": {}, "paused_until": None,
                               "monitor_ok": True, "last_run": NOW.isoformat()}, self.controls)
        self.assertNotIn("<script>", page)
        self.assertEqual(page.count("&lt;script&gt;alert(1)&lt;/script&gt;"), 3)

    def test_buttons_need_the_token(self):
        self.run_monitor()
        for form in ({"action": "pause", "hours": "1"}, {"token": "guess", "action": "pause", "hours": "1"}):
            code, _, _ = self.fetch("/action", urllib.parse.urlencode(form).encode())
            self.assertEqual(code, 403)
        self.assertNotIn("alerts paused", self.fetch("/")[2])

    def test_malformed_posts_get_an_answer(self):
        self.run_monitor()
        self.assertEqual(self.fetch("/action", "token=ä&action=run".encode())[0], 403)   # non-ASCII token
        for length in ("abc", "-1", "99999"):
            req = urllib.request.Request(self.base + "/action", data=b"x", headers={"Content-Length": length})
            try:
                urllib.request.urlopen(req, timeout=5)
                code = 200
            except urllib.error.HTTPError as e:
                code = e.code
                e.close()
            self.assertIn(code, (400, 413), length)

    def test_locked_database_answers_503(self):
        self.run_monitor()
        token = re.search(r"name='token' value='([^']+)'", self.fetch("/")[2]).group(1)
        lock = sqlite3.connect(self.db)
        lock.execute("begin exclusive")
        old, store_module.DB_TIMEOUT = store_module.DB_TIMEOUT, 0.1
        try:
            code = self.fetch("/action", urllib.parse.urlencode(
                {"token": token, "action": "pause", "hours": "1"}).encode())[0]
        finally:
            store_module.DB_TIMEOUT = old
            lock.rollback()
            lock.close()
        self.assertEqual(code, 503)

    def test_other_host_names_are_refused(self):
        # DNS rebinding: evil.example resolves to 127.0.0.1, the browser sends Host: evil.example
        port = self.server.server_port
        self.assertEqual(self.fetch("/", headers={"Host": f"evil.example:{port}"})[0], 421)
        self.assertEqual(self.fetch("/action", b"action=run", headers={"Host": f"evil.example:{port}"})[0], 421)
        self.assertEqual(self.fetch("/", headers={"Host": f"localhost:{port}"})[0], 200)

    def test_mute_suppresses_one_checks_alerts(self):
        self.run_monitor()
        code, _, body = self.press(action="mute", check="node1/ranges", hours="1")
        self.assertEqual(code, 200)
        self.assertIn("Check muted", body)
        self.assertIn("muted until", body)
        self.sent.clear()
        self.run_monitor(wall_temp_c=85.0, unexpected="node9")   # ranges fails (muted), unexpected warns (not)
        self.assertEqual(self.sent, ["WARN devices/unexpected"])
        delivery = {t["check_id"]: t["delivery"] for t in json.loads(self.fetch("/status.json")[2])["transitions"]
                    if t["alert"]}
        self.assertEqual(delivery["node1/ranges"], "muted")
        self.assertIn("Check unmuted", self.press(action="unmute", check="node1/ranges")[2])

    def test_pause_and_resume(self):
        self.run_monitor()
        self.assertIn("All alerts paused", self.press(action="pause", hours="24")[2])
        self.sent.clear()
        self.run_monitor(wall_temp_c=85.0)
        self.assertEqual(self.sent, [])
        self.assertIn("Alerts resumed", self.press(action="resume")[2])
        self.assertIn("Pause alerts 1 h", self.fetch("/")[2])

    def test_bad_button_values_are_rejected(self):
        self.run_monitor()
        for form in ({"action": "mute", "check": "node1/ranges", "hours": "9999"},
                     {"action": "mute", "check": "<made-up>", "hours": "1"},
                     {"action": "pause", "hours": "x"}, {"action": "drop-tables"}):
            self.assertEqual(self.press(**form)[0], 400, form)

    def test_test_notification(self):
        self.assertIn("Test notification sent", self.press(action="test")[2])
        self.assertEqual(self.sent, ["TEST mould-detect monitor"])

        def down(*args):
            raise urllib.error.URLError("no route")
        self.controls.send = down
        self.assertIn("Test notification failed", self.press(action="test")[2])
        self.controls.cfg = monitor.config({**ENV, "NTFY_TOPIC": ""})
        self.assertIn("NTFY_TOPIC is not set", self.press(action="test")[2])

    def test_run_now_wakes_the_loop(self):
        self.assertIn("Run requested", self.press(action="run")[2])   # no loop running: times out politely
        self.controls.run_now.clear()   # main()'s loop would have picked that request up

        def loop():   # stands in for main()'s loop: wait for the button, run, report done
            if self.controls.run_now.wait(5):
                self.controls.run_now.clear()
                self.run_monitor(runs=1)
                self.controls.run_done.set()
        threading.Thread(target=loop, daemon=True).start()
        self.assertIn("Checks ran just now", self.press(action="run")[2])


if __name__ == "__main__":
    unittest.main()
