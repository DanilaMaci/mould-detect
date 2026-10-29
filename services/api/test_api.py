"""The API over real HTTP on a free local port: endpoints, tokens, limits, metrics, load shedding, CORS.
Run: python3 -m unittest discover -s services/api"""
import http.client
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import api
import db as db_module
from db import Database
from test_validate import FIRMWARE

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
NODE1 = "node1-token-0123456789abcdef"
NODE2 = "node2-token-0123456789abcdef"
READ = "read-token-0123456789abcdefgh"


class ApiTest(unittest.TestCase):
    def setUp(self, max_in_flight=64):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.dir.name) / "api.sqlite")
        self.clock = [NOW]
        self.app = api.App(self.db, {"node1": NODE1, "node2": NODE2}, READ, max_in_flight=max_in_flight,
                           clock=lambda: self.clock[0])
        self.server = api.make_server(self.app, port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def request(self, method, path, body=None, token=None, headers=None, conn=None):
        """(status, headers, parsed JSON or text)."""
        c = conn or http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        raw = r.read()
        if conn is None:
            c.close()
        ctype = r.getheader("Content-Type", "")
        return r.status, r, (json.loads(raw) if ctype == "application/json" and raw else raw.decode())

    def post(self, reading, token=NODE1, **kw):
        return self.request("POST", "/api/readings", reading, token, **kw)

    # --- writing ------------------------------------------------------------------------------------------------

    def test_firmware_post_then_read_back(self):
        status, _, body = self.post(FIRMWARE)
        self.assertEqual((status, body), (201, {"id": 1}))
        status, _, rows = self.request("GET", "/api/readings?device_id=node1", token=READ)
        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["device_id"], r["temp_c"], r["co2_ppm"], r["door_open"], r["outdoor_temp_c"]),
                         ("node1", 21.43, 812, True, None))
        self.assertEqual(r["measured_at"], "2026-10-26T12:00:00.000000Z")

    def test_tokens_are_separated(self):
        self.assertEqual(self.post(FIRMWARE, token=None)[0], 401)
        self.assertEqual(self.post(FIRMWARE, token="guess-guess-guess-guess")[0], 401)
        self.assertEqual(self.post(FIRMWARE, token=READ)[0], 401)                 # the dashboard cannot write
        self.assertEqual(self.request("GET", "/api/readings", token=NODE1)[0], 401)   # a node cannot read
        status, _, body = self.post(FIRMWARE, token=NODE2)                         # node2 cannot write as node1
        self.assertEqual((status, body["problems"]), (422, ["device_id: does not match the token"]))

    def test_bad_requests(self):
        status, _, body = self.post({**FIRMWARE, "rh": 140, "temp_c": True})
        self.assertEqual(status, 422)
        self.assertEqual(sorted(body["problems"]), ["rh: 140 outside 0..100", "temp_c: expected float"])
        self.assertEqual(self.post(b'{"temp_c": NaN}', headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.post(json.dumps(FIRMWARE).encode(), headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post(b"{" + b" " * 5000 + b"}", headers={"Content-Type": "application/json"})[0], 413)
        self.assertEqual(self.request("GET", "/api/readings?limit=99999", token=READ)[0], 422)
        self.assertEqual(self.request("DELETE", "/api/readings", token=READ)[0], 501)
        self.assertEqual(self.db.count(), 0)

    def test_chunked_body_is_refused(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/readings", body=iter([json.dumps(FIRMWARE).encode()]),
                  headers={"Authorization": f"Bearer {NODE1}", "Content-Type": "application/json"},
                  encode_chunked=True)
        self.assertEqual(c.getresponse().status, 411)
        c.close()

    def test_keep_alive_reuses_one_connection(self):
        before = self.app.metrics.connections
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for _ in range(3):
            status, r, _ = self.post(FIRMWARE, conn=c)
            self.assertEqual((status, r.version, r.will_close), (201, 11, False))   # HTTP/1.1, connection kept
        c.close()
        self.assertEqual(self.app.metrics.connections - before, 1)   # three requests, one TCP connection
        self.assertEqual(self.db.count(), 3)

    # --- reading ------------------------------------------------------------------------------------------------

    def test_hourly_and_time_filters(self):
        for minute, temp in ((5, 20.0), (35, 22.0), (65, 30.0)):
            self.clock[0] = NOW + timedelta(minutes=minute)
            self.post({**FIRMWARE, "temp_c": temp, "window_open": minute == 5})
        since = "2026-10-26T12:00:00Z"
        status, _, rows = self.request("GET", f"/api/readings?hourly=1&since={since}&until=2026-10-26T14:00:00Z",
                                       token=READ)
        self.assertEqual(status, 200)
        self.assertEqual([(r["hour"], r["temp_c"], r["window_open"], r["samples"]) for r in rows],
                         [("2026-10-26T12:00:00.000000Z", 21.0, 0.5, 2), ("2026-10-26T13:00:00.000000Z", 30.0, 0.0, 1)])
        _, _, rows = self.request("GET", "/api/readings?since=2026-10-26T13:00:00Z&until=2026-10-26T14:00:00Z",
                                  token=READ)
        self.assertEqual([r["temp_c"] for r in rows], [30.0])

    def test_weather(self):
        self.db.upsert_weather([{"observed_at": "2026-10-26T11:00:00.000000Z", "temp_c": 9.5, "rh": 88, "dew_point_c": 7.6,
                                 "press_hpa": 1001, "precip_mm": 0, "cloud_cover_pct": 100, "wind_speed_ms": 3,
                                 "wind_dir_deg": 220, "shortwave_wm2": 40, "weather_code": 3, "is_day": 1,
                                 "fetched_at": "2026-10-26T11:30:00.000000Z"}])
        status, _, rows = self.request("GET", "/api/weather", token=READ)
        self.assertEqual(status, 200)
        self.assertEqual((rows[0]["temp_c"], rows[0]["is_day"]), (9.5, True))
        self.assertNotIn("fetched_at", rows[0])

    # --- operations -----------------------------------------------------------------------------------------------

    def test_health_metrics_and_label_cardinality(self):
        self.assertEqual(self.request("GET", "/api/health")[2], {"status": "ok", "readings": 0})
        self.post(FIRMWARE)
        for i in range(20):   # random URLs must not create new metric series
            self.request("GET", f"/random/{i}")
        status, r, text = self.request("GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/plain; version=0.0.4"))
        self.assertIn('api_http_requests_total{route="post_reading",method="POST",status="201"} 1', text)
        self.assertIn('api_http_requests_total{route="other",method="GET",status="404"} 20', text)
        self.assertNotIn("random", text)
        self.assertIn("api_readings_stored 1", text)
        self.assertNotIn("Python", r.getheader("Server"))

    def test_traffic_page_and_window(self):
        self.post(FIRMWARE)
        status, r, page = self.request("GET", "/traffic")
        self.assertEqual(status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn('<script src="/traffic.js">', page)
        self.assertEqual(self.request("GET", "/traffic.js")[0], 200)
        _, _, w = self.request("GET", "/traffic.json")
        self.assertEqual(len(w["series"]), 60)
        self.assertEqual(sum(p["rps"] for p in w["series"]), 1)   # the POST counts; the page's own GETs do not

    def test_cors_only_for_listed_origins(self):
        _, r, _ = self.request("OPTIONS", "/api/readings", headers={"Origin": "http://localhost:8000"})
        self.assertEqual(r.status, 204)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "http://localhost:8000")
        self.assertIn("Authorization", r.getheader("Access-Control-Allow-Headers"))
        _, r, _ = self.request("GET", "/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_client_gone_is_499_not_500(self):
        def gone():
            raise ConnectionResetError(54, "Connection reset by peer")
        self.db.count = gone   # stands in for a client that disconnects while the request is handled
        with self.assertRaises((http.client.RemoteDisconnected, ConnectionError)):
            self.request("GET", "/api/health")
        del self.db.count
        text = self.request("GET", "/metrics")[2]
        self.assertIn('api_http_requests_total{route="health",method="GET",status="499"} 1', text)
        self.assertNotIn('status="500"', text)

    def test_locked_database_answers_503(self):
        lock = sqlite3.connect(self.db.path)
        lock.execute("begin exclusive")
        old, db_module.BUSY_TIMEOUT = db_module.BUSY_TIMEOUT, 0.1
        self.db.local = threading.local()   # new connections pick up the short timeout
        try:
            status, r, _ = self.post(FIRMWARE)
        finally:
            db_module.BUSY_TIMEOUT = old
            lock.rollback()
            lock.close()
        self.assertEqual((status, r.getheader("Retry-After")), (503, "1"))


class LoadSheddingTest(ApiTest):
    """With room for one request at a time, a second concurrent request is refused at once."""

    def setUp(self):
        super().setUp(max_in_flight=1)

    def test_second_request_is_shed(self):
        inside, release = threading.Event(), threading.Event()
        real_count = self.db.count

        def slow_count():
            inside.set()
            release.wait(5)
            return real_count()
        self.db.count = slow_count
        first = []
        t = threading.Thread(target=lambda: first.append(self.request("GET", "/api/health")[0]))
        t.start()
        self.assertTrue(inside.wait(5))
        status, r, _ = self.request("GET", "/api/health")
        monitoring = [self.request("GET", path)[0] for path in ("/traffic.json", "/metrics")]   # still full here
        release.set()
        t.join(5)
        self.assertEqual((status, r.getheader("Retry-After"), first), (503, "1", [200]))
        self.assertEqual(monitoring, [200, 200])   # monitoring answers while the server is full
        # a shed POST keeps its connection: the body is drained instead of forcing a reconnect
        inside.clear()
        release.clear()
        t = threading.Thread(target=lambda: self.request("GET", "/api/health"))
        t.start()
        self.assertTrue(inside.wait(5))
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        status, r, _ = self.post(FIRMWARE, conn=c)
        self.assertEqual((status, r.will_close), (503, False))
        release.set()
        t.join(5)
        del self.db.count
        self.assertEqual(self.post(FIRMWARE, conn=c)[0], 201)   # same connection, next request works
        c.close()
        self.assertIn("api_http_requests_shed_total 2", self.request("GET", "/metrics")[2])

    # the inherited tests run again with a limit of 1: everything also works one request at a time


class TokensFromEnvTest(unittest.TestCase):
    def test_parsing_and_weak_tokens(self):
        devices, read = api.tokens_from_env({"API_DEVICE_TOKENS": f"node1={NODE1}, node2={NODE2}", "API_READ_TOKEN": READ})
        self.assertEqual((devices, read), ({"node1": NODE1, "node2": NODE2}, READ))
        for bad in ({"API_DEVICE_TOKENS": "node1=short"}, {"API_DEVICE_TOKENS": NODE1},
                    {"API_READ_TOKEN": "short"}, {"API_DEVICE_TOKENS": f"node1={NODE1}", "API_READ_TOKEN": NODE1}):
            with self.assertRaises(ValueError, msg=bad):
                api.tokens_from_env(bad)
        self.assertEqual(api.tokens_from_env({}), ({}, ""))


if __name__ == "__main__":
    unittest.main()
