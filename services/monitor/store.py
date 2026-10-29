"""Check state and alert history for services/monitor, in SQLite (default data/monitor.sqlite, kept local).

A result only changes a check's status after CONFIRM_RUNS runs in a row agree (debounce: one odd sample does not
alert). Every committed change is a row in `transitions`; it is an alert only when the severity differs from the
last known status (ok/off -> warn -> fail and back), so unknown in between never alerts on its own. Alerts wait in
the table until ntfy accepts them (outbox), so a network outage delays alerts instead of losing them. Alerts of a
muted check, or raised while all alerts are paused, are marked as such and never sent later (no flood afterwards).
"""
import sqlite3
from datetime import datetime, timedelta

from checks import SEVERITY, UNKNOWN

CONFIRM_RUNS = 2
DB_TIMEOUT = 5                        # seconds to wait for a lock held by the other thread
ALERT_MAX_AGE = timedelta(hours=24)   # undelivered alerts older than this are not sent any more

SCHEMA = """
create table if not exists checks (
    check_id     text primary key,
    status       text not null,          -- committed status
    message      text not null,          -- newest message, also while a change is pending
    since        text not null,          -- when the status was committed (UTC ISO)
    last_known   text,                   -- newest committed status other than unknown; alerts compare with it
    pending      text,                   -- status seen but not yet confirmed
    pending_runs integer not null default 0,
    checked_at   text not null
);
create table if not exists transitions (
    id         integer primary key,
    at         text not null,
    check_id   text not null,
    old_status text not null,
    new_status text not null,
    was        text,                     -- last known status before this change (what the alert compares with)
    message    text not null,
    alert      integer not null,         -- 1 = goes out as a notification
    sent_at    text,                     -- null until handled
    delivery   text                      -- sent, muted (check muted) or paused (all alerts paused)
);
create table if not exists mutes (check_id text primary key, until text not null);   -- set from the status page
create table if not exists meta (key text primary key, value text not null);
"""


class Store:
    def __init__(self, path, stale_after=timedelta(minutes=5)):
        """stale_after: a pending change older than this (monitor stopped, Mac asleep) starts counting again."""
        self.stale_after = stale_after
        self.db = sqlite3.connect(path, timeout=DB_TIMEOUT)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")   # the status page reads while the monitor writes
        self.db.executescript(SCHEMA)

    def update(self, results, now):
        """Apply one run's results; return the transitions committed in this run (as dicts)."""
        at = now.isoformat()
        committed = []
        muted, paused = self.mutes(now), self.paused_until(now)
        with self.db:
            for r in results:
                row = self.db.execute("select * from checks where check_id = ?", (r.check,)).fetchone()
                if row is None:   # new check: starts unknown, then goes through the same debounce as any change
                    self.db.execute("insert into checks (check_id, status, message, since, checked_at) "
                                    "values (?, ?, ?, ?, ?)", (r.check, UNKNOWN, r.message, at, at))
                    row = {"status": UNKNOWN, "last_known": None, "pending": None, "pending_runs": 0, "checked_at": at}
                if r.status == row["status"]:
                    self.db.execute("update checks set message = ?, pending = null, pending_runs = 0, checked_at = ? "
                                    "where check_id = ?", (r.message, at, r.check))
                    continue
                fresh = row["pending"] == r.status and now - datetime.fromisoformat(row["checked_at"]) <= self.stale_after
                runs = row["pending_runs"] + 1 if fresh else 1
                if runs < CONFIRM_RUNS:
                    self.db.execute("update checks set message = ?, pending = ?, pending_runs = ?, checked_at = ? "
                                    "where check_id = ?", (r.message, r.status, runs, at, r.check))
                    continue
                last_known = row["last_known"]
                alert = r.status != UNKNOWN and SEVERITY[r.status] != SEVERITY.get(last_known, 0)
                self.db.execute("update checks set status = ?, message = ?, since = ?, last_known = ?, pending = null, "
                                "pending_runs = 0, checked_at = ? where check_id = ?",
                                (r.status, r.message, at, last_known if r.status == UNKNOWN else r.status, at, r.check))
                # Raised during a pause or a mute of this check: recorded as such, never sent later
                delivery = ("paused" if paused else "muted" if r.check in muted else None) if alert else None
                t = {"at": at, "check_id": r.check, "old_status": row["status"], "new_status": r.status,
                     "was": last_known, "message": r.message, "alert": int(alert), "delivery": delivery,
                     "sent_at": at if delivery else None}
                t["id"] = self.db.execute("insert into transitions (at, check_id, old_status, new_status, was, message, "
                                          "alert, delivery, sent_at) values (:at, :check_id, :old_status, :new_status, "
                                          ":was, :message, :alert, :delivery, :sent_at)", t).lastrowid
                committed.append(t)
            # Checks that no longer exist (device or HTTP target removed from the config); history stays
            ids = [r.check for r in results]
            self.db.execute(f"delete from checks where check_id not in ({','.join('?' * len(ids))})", ids)
        return committed

    def unsent(self, now):
        """Alerts not delivered yet and younger than ALERT_MAX_AGE, oldest first."""
        return self.db.execute("select * from transitions where alert = 1 and sent_at is null and at >= ? order by id",
                               ((now - ALERT_MAX_AGE).isoformat(),)).fetchall()

    def mark_sent(self, transition_id, now, delivery="sent"):
        with self.db:
            self.db.execute("update transitions set sent_at = ?, delivery = ? where id = ?",
                            (now.isoformat(), delivery, transition_id))

    def mute(self, check_id, until):
        with self.db:
            self.db.execute("insert into mutes values (?, ?) on conflict (check_id) do update set until = excluded.until",
                            (check_id, until.isoformat()))

    def unmute(self, check_id):
        with self.db:
            self.db.execute("delete from mutes where check_id = ?", (check_id,))

    def mutes(self, now):
        """check_id -> muted-until (ISO) for mutes still running."""
        return {r["check_id"]: r["until"] for r in self.db.execute("select * from mutes").fetchall()
                if datetime.fromisoformat(r["until"]) > now}

    def paused_until(self, now):
        """End of the global alert pause (ISO), or None when not paused."""
        until = self.get_meta("paused_until")
        return until if until and datetime.fromisoformat(until) > now else None

    def checks(self):
        return self.db.execute("select * from checks order by check_id").fetchall()

    def transitions(self, limit=30):
        return self.db.execute("select * from transitions order by id desc limit ?", (limit,)).fetchall()

    def set_meta(self, key, value):
        with self.db:
            self.db.execute("insert into meta values (?, ?) on conflict (key) do update set value = excluded.value",
                            (key, value))

    def get_meta(self, key):
        row = self.db.execute("select value from meta where key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self):
        self.db.close()
