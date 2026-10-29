"""Tests for fetch_weather (to_rows, missing_hours, sync). Run: python3 -m unittest discover -s jobs"""
import copy
import unittest
from datetime import datetime, timedelta, timezone

from fetch_weather import VARIABLES, missing_hours, sync, to_rows

FETCHED_AT = datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc)

# Shape of an Open-Meteo hourly response, two hours, synthetic values
RESPONSE = {
    "hourly_units": {"time": "iso8601", **{var: unit for var, (_, unit) in VARIABLES.items()}},
    "hourly": {
        "time": ["2026-10-22T11:00", "2026-10-22T12:00"],
        "temperature_2m": [9.4, 10.1],
        "relative_humidity_2m": [88, 84],
        "dew_point_2m": [7.5, 7.5],
        "surface_pressure": [1000.2, 999.8],
        "precipitation": [0.0, 0.3],
        "cloud_cover": [100, 75],
        "wind_speed_10m": [4.2, 5.0],
        "wind_direction_10m": [225, 230],
        "shortwave_radiation": [120.0, None],
        "weather_code": [3, 61],
        "is_day": [1, 1],
    },
}
RESPONSE["hourly_units"]["is_day"] = ""


class ToRowsTest(unittest.TestCase):
    def test_columns_and_values(self):
        rows = to_rows(RESPONSE, FETCHED_AT)
        self.assertEqual(len(rows), 2)
        r = rows[1]
        self.assertEqual(r["observed_at"], "2026-10-22T12:00:00+00:00")
        self.assertEqual(r["fetched_at"], "2026-10-22T12:30:00+00:00")
        self.assertEqual(r["source"], "open-meteo")
        self.assertEqual((r["temp_c"], r["rh"], r["press_hpa"], r["precip_mm"]), (10.1, 84, 999.8, 0.3))
        self.assertIs(r["weather_code"], 61)
        self.assertIs(r["is_day"], True)
        expected_cols = {c for c, _ in VARIABLES.values()} | {"observed_at", "source", "fetched_at"}
        self.assertEqual(set(r), expected_cols)

    def test_missing_value_stays_null(self):
        self.assertIsNone(to_rows(RESPONSE, FETCHED_AT)[1]["shortwave_wm2"])

    def test_unexpected_unit_is_rejected(self):
        bad = copy.deepcopy(RESPONSE)
        bad["hourly_units"]["wind_speed_10m"] = "km/h"   # forgot wind_speed_unit=ms
        with self.assertRaises(ValueError):
            to_rows(bad, FETCHED_AT)


def hour(day, h):
    return datetime(2026, 10, day, h, tzinfo=timezone.utc)


class MissingHoursTest(unittest.TestCase):
    def test_finds_the_holes(self):
        stored = {hour(22, 0), hour(22, 1), hour(22, 4)}
        self.assertEqual(missing_hours(stored, hour(22, 0), hour(22, 4)), [hour(22, 2), hour(22, 3)])

    def test_complete_and_empty(self):
        stored = {hour(22, h) for h in range(5)}
        self.assertEqual(missing_hours(stored, hour(22, 0), hour(22, 4)), [])
        self.assertEqual(len(missing_hours(set(), hour(22, 0), hour(22, 4))), 5)


class SyncTest(unittest.TestCase):
    """sync() against a fake Open-Meteo (serves any past_days) and a fake weather_hourly table."""

    ENV = {"LATITUDE": "52.0", "LONGITUDE": "0.0", "SUPABASE_URL": "https://x", "SUPABASE_SECRET_KEY": "k"}
    NOW = datetime(2026, 10, 26, 9, 40, tzinfo=timezone.utc)

    def run_sync(self, table):
        calls = {}

        def fake_fetch(lat, lon, past_days, forecast_days):
            calls["past_days"] = past_days
            this_hour = self.NOW.replace(minute=0)
            first = this_hour.replace(hour=0) - timedelta(days=past_days)
            times = [first + timedelta(hours=i) for i in range((past_days + forecast_days) * 24 + this_hour.hour)]
            resp = copy.deepcopy(RESPONSE)
            resp["hourly"] = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
                              **{var: [1] * len(times) for var in VARIABLES}}
            return resp

        def fake_upsert(rows, url, key):
            table.update(datetime.fromisoformat(r["observed_at"]) for r in rows)

        def fake_stored(url, key, since):
            return {t for t in table if t >= since}

        left = sync(self.ENV, now=self.NOW, log=lambda *_: None, fetch_fn=fake_fetch, upsert_fn=fake_upsert,
                    stored_fn=fake_stored)
        return left, calls

    def test_fills_a_gap_three_days_back(self):
        this_hour = self.NOW.replace(minute=0)
        table = {this_hour - timedelta(hours=h) for h in range(10 * 24)}
        gap = {this_hour - timedelta(hours=h) for h in range(70, 80)}   # job not run for 10 h, ~3 days ago
        table -= gap
        left, calls = self.run_sync(table)
        self.assertEqual(left, [])
        self.assertGreaterEqual(calls["past_days"], 4)
        self.assertTrue(gap <= table, "the gap is filled")

    def test_no_gap_only_refreshes_two_days(self):
        this_hour = self.NOW.replace(minute=0)
        table = {this_hour - timedelta(hours=h) for h in range(5 * 24)}
        left, calls = self.run_sync(table)
        self.assertEqual((left, calls["past_days"]), ([], 2))

    def test_empty_table_gets_the_first_sync_window(self):
        left, calls = self.run_sync(set())
        self.assertEqual(left, [])
        self.assertEqual(calls["past_days"], 32)

    def test_empty_setting_counts_as_missing(self):   # GitHub Actions passes an unset secret as ""
        env = {"LATITUDE": "", "LONGITUDE": "1.0", "SUPABASE_URL": "https://x", "SUPABASE_SECRET_KEY": "k"}
        with self.assertRaises(KeyError) as cm:
            sync(env=env, fetch_fn=None, upsert_fn=None, stored_fn=None)
        self.assertEqual(cm.exception.args[0], "LATITUDE")


if __name__ == "__main__":
    unittest.main()
