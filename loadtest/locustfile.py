"""Locust scenario for services/api: simulated sensor nodes and dashboard viewers.

Run through loadtest/ramp.py (starts a throwaway API, seeds it, ramps until it breaks), or by hand against an API
you started yourself:  .venv/bin/locust -f loadtest/locustfile.py --host http://127.0.0.1:8201
Tokens come from LOADTEST_DEVICE_TOKEN (a device token of that API) and LOADTEST_READ_TOKEN.

The mix: 9 of 10 users are sensor nodes posting one reading per second (60x the real node's rate, so a few hundred
users stand for a building full of sensors); 1 of 10 is a person with the 3D dashboard open: page load (24 h of
readings + weather), then polling for new rows, sometimes the 7-day view or the health check.
"""
import os
import random
from datetime import datetime, timedelta, timezone

import gevent
from locust import FastHttpUser, constant_throughput, task

DEVICE_TOKEN = os.environ.get("LOADTEST_DEVICE_TOKEN", "")
READ_TOKEN = os.environ.get("LOADTEST_READ_TOKEN", "")
VIEWED_DEVICE = "node1"   # ramp.py seeds a day of minute rows for it
# Real nodes boot at random moments, so their once-per-interval posts are spread out. LOADTEST_SYNC=1 starts every
# node on the same beat instead (all nodes rebooting after a power cut): the same average rate, arriving in bursts.
SYNC = os.environ.get("LOADTEST_SYNC") == "1"


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


class SensorNode(FastHttpUser):
    """POSTs a reading every second, same JSON as the ESP32 (device id comes from the token)."""
    weight = 9
    wait_time = constant_throughput(1)

    def on_start(self):
        if not SYNC:
            gevent.sleep(random.random())   # cooperative: the other simulated users keep running

    @task
    def post_reading(self):
        reading = {"temp_c": round(random.uniform(19, 23), 2), "rh": round(random.uniform(45, 65), 2),
                   "press_hpa": round(random.uniform(995, 1010), 2), "rssi_dbm": random.randint(-80, -50),
                   "co2_ppm": random.randint(450, 1500), "scd_temp_c": round(random.uniform(19, 24), 2),
                   "scd_rh": round(random.uniform(40, 65), 2), "wall_temp_c": round(random.uniform(14, 18), 2),
                   "outdoor_temp_c": None, "window_open": random.random() < 0.1, "door_open": True}
        self.client.post("/api/readings", json=reading, headers={"Authorization": f"Bearer {DEVICE_TOKEN}"},
                         name="POST /api/readings")


class DashboardViewer(FastHttpUser):
    """Someone with the dashboard open: loads the page once, then mostly polls for new rows."""
    weight = 1
    wait_time = constant_throughput(0.5)

    def on_start(self):
        self.load_page()

    def get(self, path, params, name):
        self.client.get(path, params=params, headers={"Authorization": f"Bearer {READ_TOKEN}"}, name=name)

    def load_page(self):
        now = datetime.now(timezone.utc)
        self.get("/api/readings", {"device_id": VIEWED_DEVICE, "since": iso(now - timedelta(hours=24)),
                                   "limit": 5000}, "GET readings 24h")
        self.get("/api/weather", {"since": iso(now - timedelta(hours=24)), "until": iso(now + timedelta(hours=48))},
                 "GET weather")

    @task(10)
    def poll_new_rows(self):
        self.get("/api/readings", {"device_id": VIEWED_DEVICE,
                                   "since": iso(datetime.now(timezone.utc) - timedelta(minutes=1))}, "GET readings new")

    @task(2)
    def reload_page(self):
        self.load_page()

    @task(1)
    def week_view(self):
        self.get("/api/readings", {"device_id": VIEWED_DEVICE, "hourly": 1,
                                   "since": iso(datetime.now(timezone.utc) - timedelta(days=7))}, "GET readings 7d hourly")

    @task(1)
    def health(self):
        self.client.get("/api/health", name="GET /api/health")
