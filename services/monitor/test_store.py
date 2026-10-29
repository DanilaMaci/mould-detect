"""Tests for the debounce, alert and outbox rules of the state store. Run: python3 -m unittest discover -s services/monitor"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from checks import FAIL, OFF, OK, UNKNOWN, WARN, Result
from store import Store

T0 = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "monitor.sqlite"
        self.store = Store(self.path)
        self.minute = 0

    def tearDown(self):
        self.store.close()
        self.dir.cleanup()

    def run_statuses(self, *statuses, check="node1/silent"):
        """Feed one result per run; return all transitions committed, as (old, new, alert)."""
        out = []
        for s in statuses:
            self.minute += 1
            for t in self.store.update([Result(check, s, f"run {self.minute}")], T0 + self.minute * MIN):
                out.append((t["old_status"], t["new_status"], t["alert"]))
        return out

    def status(self, check="node1/silent"):
        return {r["check_id"]: r["status"] for r in self.store.checks()}[check]

    def test_new_check_ok_commits_after_two_runs_without_alert(self):
        self.assertEqual(self.run_statuses(OK), [])
        self.assertEqual(self.status(), UNKNOWN)
        self.assertEqual(self.run_statuses(OK), [(UNKNOWN, OK, 0)])

    def test_new_check_failing_alerts(self):
        self.assertEqual(self.run_statuses(FAIL, FAIL), [(UNKNOWN, FAIL, 1)])

    def test_single_bad_run_does_not_alert(self):
        self.run_statuses(OK, OK)
        self.assertEqual(self.run_statuses(FAIL, OK, FAIL, OK, OK), [])
        self.assertEqual(self.status(), OK)

    def test_change_and_recovery_alert_once_each(self):
        self.run_statuses(OK, OK)
        self.assertEqual(self.run_statuses(WARN, WARN, WARN), [(OK, WARN, 1)])
        self.assertEqual(self.run_statuses(FAIL, FAIL), [(WARN, FAIL, 1)])
        self.assertEqual(self.run_statuses(OK, OK), [(FAIL, OK, 1)])

    def test_unknown_in_between_compares_with_last_known(self):
        self.run_statuses(OK, OK)
        # ok -> unknown (Supabase down) -> fail: one alert, for the fail
        self.assertEqual(self.run_statuses(UNKNOWN, UNKNOWN, FAIL, FAIL), [(OK, UNKNOWN, 0), (UNKNOWN, FAIL, 1)])
        # fail -> unknown -> fail again: nothing new to say
        self.assertEqual(self.run_statuses(UNKNOWN, UNKNOWN, FAIL, FAIL), [(FAIL, UNKNOWN, 0), (UNKNOWN, FAIL, 0)])
        last = self.store.transitions(1)[0]
        self.assertEqual(last["was"], FAIL)

    def test_off_and_ok_are_the_same_severity(self):
        self.run_statuses(OFF, OFF)
        self.assertEqual(self.run_statuses(OK, OK), [(OFF, OK, 0)])

    def test_pending_change_does_not_survive_a_long_gap(self):
        self.run_statuses(OK, OK, FAIL)
        self.minute += 60   # monitor stopped / Mac asleep for an hour
        self.assertEqual(self.run_statuses(FAIL), [])   # counts as the first of two again
        self.assertEqual(self.run_statuses(FAIL), [(OK, FAIL, 1)])

    def test_pending_change_is_visible(self):
        self.run_statuses(OK, OK, FAIL)
        row = self.store.checks()[0]
        self.assertEqual((row["status"], row["pending"], row["pending_runs"], row["message"]), (OK, FAIL, 1, "run 3"))

    def test_state_survives_a_restart(self):
        self.run_statuses(FAIL, FAIL)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.run_statuses(FAIL, FAIL), [])   # no second alert after restarting the monitor

    def test_removed_checks_are_dropped_but_history_stays(self):
        self.run_statuses(FAIL, FAIL, check="http/old")
        self.run_statuses(OK, check="node1/silent")
        self.assertEqual([r["check_id"] for r in self.store.checks()], ["node1/silent"])
        self.assertEqual(self.store.transitions()[0]["check_id"], "http/old")

    def test_outbox(self):
        self.run_statuses(OK, OK, FAIL, FAIL)
        now = T0 + self.minute * MIN
        pending = self.store.unsent(now)
        self.assertEqual([t["new_status"] for t in pending], [FAIL])
        self.store.mark_sent(pending[0]["id"], now)
        self.assertEqual(self.store.unsent(now), [])

    def test_old_undelivered_alerts_expire(self):
        self.run_statuses(FAIL, FAIL)
        self.assertEqual(len(self.store.unsent(T0 + 2 * MIN)), 1)
        self.assertEqual(self.store.unsent(T0 + timedelta(hours=25)), [])


if __name__ == "__main__":
    unittest.main()
