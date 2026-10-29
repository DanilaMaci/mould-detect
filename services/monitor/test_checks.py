"""Tests for the check rules. Run: python3 -m unittest discover -s services/monitor"""
import unittest
from datetime import datetime, timedelta, timezone

import checks
from checks import FAIL, OFF, OK, UNKNOWN, WARN, Snapshot, evaluate

NOW = datetime(2026, 10, 26, 12, 30, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)

GOOD = {"temp_c": 21.3, "rh": 55.2, "press_hpa": 1002.4, "co2_ppm": 800, "scd_temp_c": 21.9, "scd_rh": 53.0,
        "wall_temp_c": 17.25, "outdoor_temp_c": 8.5}


def rows(minutes, device="node1", vary=True, **override):
    """One row per minute for the last `minutes` minutes, oldest first; values drift unless vary=False."""
    out = []
    for i in range(minutes, 0, -1):
        t = NOW - i * MIN
        r = {"device_id": device, "measured_at": t, "received_at": t}
        for col, v in GOOD.items():
            r[col] = v + (i % 7) * 0.01 if vary and col != "co2_ppm" else v + (i % 7 if vary else 0)
        r.update(override)
        out.append(r)
    return out


def snapshot(window_rows, **kw):
    snap = Snapshot(devices=["node1"], rows=window_rows,
                    last_received={"node1": window_rows[-1]["received_at"] if window_rows else None},
                    probe_seen={("node1", c): NOW - MIN for c in checks.PROBES},
                    weather_hours={NOW.replace(minute=0) - timedelta(hours=h) for h in range(80)},
                    weather_fetched_at=NOW - 20 * MIN)
    for k, v in kw.items():
        setattr(snap, k, v)
    return snap


def by_id(results):
    return {r.check: r for r in results}


class NodeSilentTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(checks.node_silent("node1", NOW - 4 * MIN, NOW).status, OK)
        self.assertEqual(checks.node_silent("node1", NOW - 5 * MIN, NOW).status, WARN)
        self.assertEqual(checks.node_silent("node1", NOW - 15 * MIN, NOW).status, FAIL)
        self.assertEqual(checks.node_silent("node1", None, NOW).status, FAIL)

    def test_message_has_age(self):
        self.assertEqual(checks.node_silent("node1", NOW - 7 * MIN, NOW).message, "last row 7 min ago")


class RangeTest(unittest.TestCase):
    def test_plausible(self):
        self.assertEqual(checks.out_of_range("node1", rows(3)).status, OK)

    def test_ds18b20_power_on_value_fails(self):
        r = checks.out_of_range("node1", rows(3, wall_temp_c=85.0))
        self.assertEqual(r.status, FAIL)
        self.assertIn("wall_temp_c 85 outside", r.message)

    def test_only_newest_row_counts_and_nulls_are_ignored(self):
        window = rows(3, outdoor_temp_c=None)
        window[0]["rh"] = 100.0   # an old bad value, already recovered
        self.assertEqual(checks.out_of_range("node1", window).status, OK)


class StuckTest(unittest.TestCase):
    def test_frozen_rh_warns(self):
        window = rows(40)
        for r in window:
            r["rh"] = 48.17
        result = checks.stuck_values("node1", window, NOW)
        self.assertEqual(result.status, WARN)
        self.assertIn("rh at 48.17", result.message)
        self.assertNotIn("temp_c", result.message)

    def test_changing_values_ok(self):
        self.assertEqual(checks.stuck_values("node1", rows(180), NOW).status, OK)

    def test_constant_probes_are_not_stuck(self):
        # DS18B20 at 0.0625 °C steps: a heated wall can hold one value all night
        window = rows(240)
        for r in window:
            r["wall_temp_c"], r["outdoor_temp_c"] = 17.25, 4.5
        self.assertEqual(checks.stuck_values("node1", window, NOW).status, OK)

    def test_too_little_data_is_not_judged(self):
        # node just started: 10 identical values are not evidence of a stuck sensor
        self.assertEqual(checks.stuck_values("node1", rows(10, vary=False), NOW).status, OK)


class ProbeTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(checks.probe("node1", "wall_temp_c", None, NOW).status, OFF)
        self.assertEqual(checks.probe("node1", "wall_temp_c", NOW - 2 * MIN, NOW).status, OK)
        lost = checks.probe("node1", "outdoor_temp_c", NOW - 11 * MIN, NOW)
        self.assertEqual((lost.check, lost.status), ("node1/outdoor_probe", FAIL))


class WeatherTest(unittest.TestCase):
    def test_gap_reported_with_first_hour(self):
        hours = {NOW.replace(minute=0) - timedelta(hours=h) for h in range(80)} - {datetime(2026, 10, 25, 3, tzinfo=timezone.utc)}
        r = checks.weather_gaps(hours, NOW)
        self.assertEqual(r.status, WARN)
        self.assertIn("1 missing hour(s)", r.message)
        self.assertIn("2026-10-25 03:00", r.message)

    def test_stale_sync(self):
        self.assertEqual(checks.weather_fresh(NOW - 2 * timedelta(hours=1), NOW).status, OK)
        self.assertEqual(checks.weather_fresh(NOW - 4 * timedelta(hours=1), NOW).status, WARN)
        self.assertEqual(checks.weather_fresh(None, NOW).status, WARN)


class EvaluateTest(unittest.TestCase):
    def test_healthy_pipeline_all_ok(self):
        results = evaluate(snapshot(rows(180)), NOW)
        self.assertEqual({r.status for r in results}, {OK}, [r for r in results if r.status != OK])

    def test_supabase_down_makes_data_checks_unknown_with_the_same_ids(self):
        healthy = evaluate(snapshot(rows(180)), NOW)
        down = evaluate(Snapshot(devices=["node1"], error="HTTP 503 Service Unavailable"), NOW)
        self.assertEqual([r.check for r in down], [r.check for r in healthy])
        self.assertEqual(by_id(down)["supabase"].status, FAIL)
        self.assertEqual({r.status for r in down if r.check != "supabase"}, {UNKNOWN})

    def test_silent_node_is_one_failure_not_many(self):
        old = [dict(r, measured_at=r["measured_at"] - 30 * MIN, received_at=r["received_at"] - 30 * MIN)
               for r in rows(150)]
        results = by_id(evaluate(snapshot(old, probe_seen={}), NOW))
        self.assertEqual(results["node1/silent"].status, FAIL)
        for c in ("node1/ranges", "node1/stuck", "node1/scd40", "node1/wall_probe", "node1/outdoor_probe"):
            self.assertEqual(results[c].status, UNKNOWN, c)

    def test_lost_probe_while_node_sends(self):
        seen = {("node1", "co2_ppm"): NOW - MIN, ("node1", "wall_temp_c"): NOW - 25 * MIN,
                ("node1", "outdoor_temp_c"): None}
        results = by_id(evaluate(snapshot(rows(180), probe_seen=seen), NOW))
        self.assertEqual(results["node1/wall_probe"].status, FAIL)
        self.assertEqual(results["node1/outdoor_probe"].status, OFF)
        self.assertEqual(results["node1/scd40"].status, OK)

    def test_unexpected_device_ids_are_listed_truncated_and_cleaned(self):
        others = {"a" * 100, "<img src=x>"} | {f"d{i}" for i in range(5)}
        r = by_id(evaluate(snapshot(rows(180), other_devices=others), NOW))["devices/unexpected"]
        self.assertEqual(r.status, WARN)
        self.assertIn("7 unexpected", r.message)
        self.assertIn("?img?src?x?, " + "a" * 32 + ",", r.message)   # cleaned, sorted, cut to 32
        self.assertNotIn("a" * 33, r.message)
        self.assertTrue(r.message.endswith(" ..."))

    def test_http_targets(self):
        results = by_id(evaluate(snapshot(rows(180), http={"dashboard": (200, None), "api": (502, None),
                                                            "proxy": (None, "cannot connect (refused)")}), NOW))
        self.assertEqual(results["http/dashboard"].status, OK)
        self.assertEqual(results["http/api"].status, FAIL)
        self.assertEqual(results["http/proxy"].message, "cannot connect (refused)")



class FmtAgeTest(unittest.TestCase):   # 2026-10-29 screenshot: "co2_ppm -0 s ago" (node clock slightly ahead)
    def test_small_clock_skew_reads_as_zero(self):
        self.assertEqual(checks.fmt_age(timedelta(seconds=-0.4)), "0 s")
        self.assertEqual(checks.fmt_age(timedelta(seconds=-30)), "0 s")

    def test_large_skew_stays_visible(self):
        self.assertEqual(checks.fmt_age(timedelta(seconds=-300)), "-300 s")
        self.assertEqual(checks.fmt_age(timedelta(seconds=90)), "90 s")

if __name__ == "__main__":
    unittest.main()
