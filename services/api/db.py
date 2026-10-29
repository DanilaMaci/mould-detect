"""SQLite storage for services/api (default data/api.sqlite, kept local like all house data).

One connection per thread (sqlite3 connections must stay in the thread that made them). WAL mode lets readers run
while one writer writes; writers still take turns, and a writer that waits longer than BUSY_TIMEOUT gets
sqlite3.OperationalError, which the API answers with 503. That queue is one of the places the API will break
under load.
"""
import sqlite3
import threading
from datetime import timezone

from validate import FIELDS

BUSY_TIMEOUT = 5   # seconds a writer waits for the lock

SCHEMA = f"""
create table if not exists readings (
    id          integer primary key,
    received_at text not null,          -- UTC ISO 8601, server clock
    measured_at text not null,          -- UTC ISO 8601, device clock (or received_at)
    device_id   text not null,
    {', '.join(f'{name} {"integer" if kind in (int, bool) else "real"}' for name, (kind, *_) in FIELDS.items())}
);
create index if not exists readings_device_time on readings (device_id, measured_at);
create table if not exists weather_hourly (
    observed_at text primary key,       -- UTC ISO 8601, start of the hour
    temp_c real, rh real, dew_point_c real, press_hpa real, precip_mm real, cloud_cover_pct real,
    wind_speed_ms real, wind_dir_deg real, shortwave_wm2 real, weather_code integer, is_day integer,
    fetched_at text
);
"""
COLUMNS = ["device_id", "received_at", "measured_at", *FIELDS]
WEATHER_COLUMNS = ["observed_at", "temp_c", "rh", "dew_point_c", "press_hpa", "precip_mm", "cloud_cover_pct",
                   "wind_speed_ms", "wind_dir_deg", "shortwave_wm2", "weather_code", "is_day", "fetched_at"]
BOOLS = [name for name, (kind, *_) in FIELDS.items() if kind is bool]


def iso(t):
    """Aware datetime -> fixed-width UTC text, so text order is time order (SQLite has no timestamp type)."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.local = threading.local()
        self.conn().executescript(SCHEMA)

    def conn(self):
        c = getattr(self.local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT, isolation_level=None)   # autocommit
            c.row_factory = sqlite3.Row
            c.execute("pragma journal_mode=wal")
            c.execute("pragma synchronous=normal")   # WAL + normal: safe after a crash, faster than full
            self.local.conn = c
        return c

    def insert_reading(self, row, received_at):
        values = {**row, "received_at": iso(received_at), "measured_at": iso(row["measured_at"])}
        cur = self.conn().execute(f"insert into readings ({', '.join(COLUMNS)}) values "
                                  f"({', '.join(':' + c for c in COLUMNS)})", values)
        return cur.lastrowid

    def readings(self, device_id, since, until, limit):
        sql = (f"select {', '.join(COLUMNS[2:])}, device_id from readings where measured_at >= ? and measured_at <= ?"
               + (" and device_id = ?" if device_id else "") + " order by measured_at limit ?")
        args = [iso(since), iso(until)] + ([device_id] if device_id else []) + [limit]
        return [self._row(r) for r in self.conn().execute(sql, args)]

    def readings_hourly(self, device_id, since, until, limit):
        """Hourly averages like Supabase's readings_hourly view; window_open/door_open = fraction of the hour."""
        avgs = ", ".join(f"avg({c}) as {c}" for c in FIELDS if c != "rssi_dbm")
        sql = (f"select substr(measured_at, 1, 13) || ':00:00.000000Z' as hour, device_id, {avgs}, count(*) as samples "
               "from readings where measured_at >= ? and measured_at <= ?" + (" and device_id = ?" if device_id else "")
               + " group by hour, device_id order by hour limit ?")
        args = [iso(since), iso(until)] + ([device_id] if device_id else []) + [limit]
        return [dict(r) for r in self.conn().execute(sql, args)]

    def weather(self, since, until, limit):
        rows = self.conn().execute(f"select {', '.join(WEATHER_COLUMNS[:-1])} from weather_hourly "
                                   "where observed_at >= ? and observed_at <= ? order by observed_at limit ?",
                                   (iso(since), iso(until), limit))
        return [dict(r, is_day=None if r["is_day"] is None else bool(r["is_day"])) for r in rows]

    def upsert_weather(self, rows):
        names = ", ".join(WEATHER_COLUMNS)
        with self.conn() as c:
            c.execute("begin")
            c.executemany(f"insert or replace into weather_hourly ({names}) values "
                          f"({', '.join(':' + n for n in WEATHER_COLUMNS)})", rows)

    def insert_many(self, rows):
        """Rows already in storage form (imports): one transaction, much faster than one commit per row."""
        with self.conn() as c:
            c.execute("begin")
            c.executemany(f"insert into readings ({', '.join(COLUMNS)}) values "
                          f"({', '.join(':' + c for c in COLUMNS)})", rows)

    def latest(self, column):
        r = self.conn().execute(f"select max({column}) from {'weather_hourly' if column == 'observed_at' else 'readings'}")
        return r.fetchone()[0]

    def count(self):
        return self.conn().execute("select count(*) from readings").fetchone()[0]

    def _row(self, r):
        d = dict(r)
        for b in BOOLS:
            if d[b] is not None:
                d[b] = bool(d[b])
        return d
