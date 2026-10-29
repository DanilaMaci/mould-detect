"""Tests for the Supabase import (fake Supabase answers). Run: python3 -m unittest discover -s services/api"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import import_supabase
from db import COLUMNS, WEATHER_COLUMNS, Database

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class FakeSupabase:
    """Applies the gt./eq. filters, order and limit the importer uses; counts the calls."""

    def __init__(self, readings, weather):
        self.tables = {"indoor_readings": readings, "weather_hourly": weather}
        self.calls = 0

    def get(self, table, params):
        self.calls += 1
        rows = self.tables[table]
        for col, cond in params.items():
            if not isinstance(cond, str):
                continue
            if cond.startswith("gt."):
                rows = [r for r in rows if datetime.fromisoformat(r[col]) > datetime.fromisoformat(cond[3:])]
            elif cond.startswith("eq."):
                rows = [r for r in rows if r.get(col) == cond[3:]]
        rows = sorted(rows, key=lambda r: r[params["order"]])
        return [{c: r.get(c) for c in params["select"].split(",")} for r in rows[:params["limit"]]]


def reading(minutes_ago):
    t = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"device_id": "node1", "received_at": t, "measured_at": t, "temp_c": 21.0, "rh": 50.0, "press_hpa": 1000.0,
            "rssi_dbm": -60, "co2_ppm": 700, "scd_temp_c": None, "scd_rh": None, "wall_temp_c": 17.0,
            "outdoor_temp_c": None, "window_open": False, "door_open": True}


def weather(hours_ago):
    t = (NOW.replace(minute=0) - timedelta(hours=hours_ago)).isoformat()
    return {"observed_at": t, "source": "open-meteo", "temp_c": 9.0, "rh": 80.0, "dew_point_c": 5.7, "press_hpa": 1000.0,
            "precip_mm": 0.0, "cloud_cover_pct": 50.0, "wind_speed_ms": 3.0, "wind_dir_deg": 200.0, "shortwave_wm2": 0.0,
            "weather_code": 2, "is_day": True, "fetched_at": NOW.isoformat()}


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.dir.name) / "api.sqlite")

    def tearDown(self):
        self.dir.cleanup()

    def test_pages_then_increments(self):
        fake = FakeSupabase([reading(m) for m in range(2500, 0, -1)], [weather(h) for h in range(100)])
        self.assertEqual(import_supabase.import_all(self.db, fake.get, NOW, log=lambda *a: None), (2500, 100))
        self.assertEqual(self.db.count(), 2500)
        self.assertGreaterEqual(fake.calls, 4)   # three pages of readings (1000 + 1000 + 500), one of weather
        fake.tables["indoor_readings"].append(reading(-1))   # one new row since
        n, w = import_supabase.import_all(self.db, fake.get, NOW, log=lambda *a: None)
        self.assertEqual((n, self.db.count()), (1, 2501))   # only the new row, no duplicates
        self.assertEqual(w, 72)   # the 3 days (72 hours) up to the newest stored hour are refreshed

    def test_values_survive_the_copy(self):
        fake = FakeSupabase([reading(5)], [weather(1)])
        import_supabase.import_all(self.db, fake.get, NOW, log=lambda *a: None)
        r = self.db.readings("node1", NOW - timedelta(hours=1), NOW, 10)[0]
        self.assertEqual((r["temp_c"], r["door_open"], r["window_open"], r["measured_at"]),
                         (21.0, True, False, "2026-10-26T11:55:00.000000Z"))
        w = self.db.weather(NOW - timedelta(hours=2), NOW, 10)[0]
        self.assertEqual((w["observed_at"], w["is_day"], w["weather_code"]), ("2026-10-26T11:00:00.000000Z", True, 2))
        self.assertEqual(set(COLUMNS) | set(WEATHER_COLUMNS), set(COLUMNS) | set(WEATHER_COLUMNS))


if __name__ == "__main__":
    unittest.main()
