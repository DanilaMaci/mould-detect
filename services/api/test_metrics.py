"""Tests for the API's metrics: percentiles, the Prometheus histogram, the rolling window.
Run: python3 -m unittest discover -s services/api"""
import re
import unittest

from metrics import Metrics, percentile


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PercentileTest(unittest.TestCase):
    def test_nearest_rank(self):
        values = list(range(1, 101))   # 1..100
        self.assertEqual((percentile(values, 50), percentile(values, 95), percentile(values, 99)), (50, 95, 99))
        self.assertEqual(percentile([7], 99), 7)
        self.assertIsNone(percentile([], 50))
        self.assertEqual(percentile([1, 2, 3, 1000], 50), 2)   # the outlier does not move the median
        self.assertEqual(percentile([1, 2, 3], 50), 2)           # rank 1.5 rounds up
        self.assertEqual(percentile([10, 20, 30, 40], 99), 40)   # rank 3.96 rounds up: the slowest one


class PrometheusTest(unittest.TestCase):
    def test_histogram_is_cumulative_and_consistent(self):
        m = Metrics()
        for seconds in (0.0004, 0.005, 0.005, 0.2, 30.0):   # 0.005 sits exactly on a bucket bound
            m.started()
            m.finished("post_reading", "POST", 201, seconds)
        text = m.prometheus()
        bucket = lambda le: int(re.search(rf'_bucket{{route="post_reading",le="{re.escape(le)}"}} (\d+)', text).group(1))
        self.assertEqual(bucket("0.001"), 1)
        self.assertEqual(bucket("0.005"), 3)   # le means "less than or equal"
        self.assertEqual(bucket("0.25"), 4)
        self.assertEqual(bucket("10"), 4)
        self.assertEqual(bucket("+Inf"), 5)
        self.assertIn('api_http_request_duration_seconds_count{route="post_reading"} 5', text)
        self.assertIn('api_http_requests_total{route="post_reading",method="POST",status="201"} 5', text)
        self.assertIn("api_http_requests_in_flight 0", text)
        # every metric family has exactly one TYPE line, before its samples
        types = re.findall(r"^# TYPE (\S+)", text, re.M)
        self.assertEqual(len(types), len(set(types)))


class PeakTest(unittest.TestCase):
    def test_peak_in_flight_per_second(self):
        clock = FakeClock()
        m = Metrics(clock)
        for _ in range(5):        # five overlapping requests in second 1000
            m.started()
        for _ in range(5):
            m.finished("get_readings", "GET", 200, 0.01)
        clock.t = 1001.5
        m.started()
        m.finished("get_readings", "GET", 200, 0.01)
        clock.t = 1002.1
        w = m.window(10)
        self.assertEqual(w["in_flight_peak"], 5)
        self.assertEqual([p["in_flight_peak"] for p in w["series"][-3:]], [5, 1, 0])


class WindowTest(unittest.TestCase):
    def test_rate_errors_percentiles_and_trim(self):
        clock = FakeClock()
        m = Metrics(clock)
        for i in range(100):   # 10 s with 10 requests per second; every 10th is a 500
            clock.t = 1000 + i / 10
            m.started()
            m.finished("get_readings", "GET", 500 if i % 10 == 0 else 200, (i % 10 + 1) / 1000)
        m.started()
        m.finished("traffic", "GET", 200, 0.5, live=False)   # the page's own polling is not traffic
        clock.t = 1010.2
        w = m.window(10)
        self.assertEqual(w["rps"], 10.0)
        self.assertEqual(w["error_pct"], 10.0)
        self.assertEqual((w["p50_ms"], w["p99_ms"]), (5.0, 10.0))
        self.assertEqual(w["status"], {"200": 90, "500": 10})
        self.assertEqual(w["in_flight_peak"], 1)   # requests here ran one after another
        self.assertEqual(len(w["series"]), 60)
        self.assertEqual(w["series"][-2]["rps"], 10)
        clock.t = 1100   # a minute and a half later the window is empty
        w = m.window(10)
        self.assertEqual((w["rps"], w["p99_ms"], sum(p["rps"] for p in w["series"])), (0.0, None, 0))


if __name__ == "__main__":
    unittest.main()
