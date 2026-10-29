"""Tests for the ramp's step logic (when to add users, when a step counts as broken).
Run: .venv/bin/python -m unittest discover -s loadtest   (needs Locust, installed in .venv)"""
import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.update(RAMP_STEP_USERS="50", RAMP_STEP_SECONDS="10", RAMP_MAX_USERS="200")
from ramp_shape import StepRamp   # noqa: E402


class FakeTotal:
    def __init__(self):
        self.num_requests, self.num_failures, self.p95 = 0, 0, 20

    def get_current_response_time_percentile(self, p):
        return {0.5: 5, 0.95: self.p95, 0.99: self.p95 * 2}[p]


class StepRampTest(unittest.TestCase):
    def setUp(self):
        self.total = FakeTotal()
        self.shape = StepRamp()
        self.shape.runner = SimpleNamespace(stats=SimpleNamespace(total=self.total), current_cpu_usage=12.0,
                                            environment=SimpleNamespace(host="http://127.0.0.1:1"))   # nothing there
        self.time = 0.0
        self.shape.get_run_time = lambda: self.time
        self.out = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        os.environ["RAMP_OUT"] = self.out.name

    def tearDown(self):
        os.unlink(self.out.name)

    def at(self, seconds, requests=0, failures=0, p95=20):
        """Advance to `seconds`, with `requests`/`failures` made during the step that just ended."""
        self.total.num_requests += requests
        self.total.num_failures += failures
        self.total.p95 = p95
        self.time = seconds
        return self.shape.tick()

    def test_adds_a_step_of_users_every_step(self):
        self.assertEqual(self.at(0), (50, 50))
        self.assertEqual(self.at(9.9), (50, 50))
        self.assertEqual(self.at(10, requests=480), (100, 50))
        self.assertEqual(self.shape.steps[0]["rps"], 48.0)
        self.assertEqual(self.shape.steps[0]["server"], "no answer")

    def test_stops_when_one_percent_fail(self):
        self.at(0)
        self.assertEqual(self.at(10, requests=1000, failures=10), (100, 50))   # exactly 1 %: still fine
        self.assertIsNone(self.at(20, requests=1000, failures=11))             # 1.1 %: broken
        self.assertIn("broke at 100 users", self.shape.verdict)

    def test_stops_when_p95_over_a_second(self):
        self.at(0)
        self.assertIsNone(self.at(10, requests=500, p95=1200))
        self.assertIn("p95 1200 ms", self.shape.verdict)

    def test_failures_are_counted_per_step_not_overall(self):
        self.at(0)
        self.at(10, requests=100, failures=1)           # 1 % in step 1
        self.assertEqual(self.at(20, requests=10_000), (150, 50))   # 0 % in step 2 although 1 failure overall
        self.assertEqual(self.shape.steps[1]["fail_pct"], 0.0)

    def test_stops_at_max_users(self):
        for step in range(4):
            self.assertIsNotNone(self.at(step * 10, requests=100))
        self.assertIsNone(self.at(40, requests=100))
        self.assertIn("without breaking", self.shape.verdict)


if __name__ == "__main__":
    unittest.main()
