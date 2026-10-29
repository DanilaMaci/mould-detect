# loadtest

Simulated traffic against `services/api`, increased step by step until the API breaks. Uses
[Locust](https://locust.io), installed only in the project's virtual environment `.venv` (not committed):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install locust     # behind a TLS-inspecting proxy add --use-deprecated=legacy-certs
```

## Run

```sh
.venv/bin/python loadtest/ramp.py                       # automatic ramp until it breaks (a few minutes)
.venv/bin/python loadtest/ramp.py --max-in-flight 1024  # same ramp, API with a higher shedding limit (default 400)
LOADTEST_SYNC=1 .venv/bin/python loadtest/ramp.py       # all simulated nodes post on the same beat
.venv/bin/python loadtest/ramp.py --ui                  # you drive: Locust's page on http://127.0.0.1:8089
```

While it runs, open the throwaway API's own live page: http://127.0.0.1:8201/traffic.

`ramp.py` never touches your real data: it starts a separate API on port 8201 with random tokens and its own
database inside the results folder, seeded with a day of readings so dashboard queries cost what they cost for you.
Results go to a new folder each run, `data/loadtests/<date>_<time>_<label>/`:

| File | Content |
|---|---|
| `ramp.json` | one row per step (users, offered and achieved requests/s, failures, p50/p95/p99, the API's own view) and the verdict |
| `report.html` | Locust's report with charts (open in a browser) |
| `locust_stats.csv`, `locust_stats_history.csv`, `locust_failures.csv` | raw numbers per request type / over time |
| `api_metrics.txt` | the API's `/metrics` at the end (requests by status, latency histogram, connections, shed) |
| `api.log`, `run.json` | the API's output; settings and machine |

## What the simulated users do

- **Sensor node** (9 of 10 users): POSTs a reading every second — the ESP32's JSON, 60x its real rate. By default
  each node starts at a random moment, so posts are spread over the second like real nodes; `LOADTEST_SYNC=1` lines
  them all up (a power cut that reboots every node at once): the same average rate, arriving in bursts.
- **Dashboard viewer** (1 of 10): loads the page (24 h of readings + weather), then mostly polls for new rows,
  sometimes reloads, opens the 7-day hourly view or checks `/api/health`; about one request every 2 s.

## The ramp and the verdict

`ramp_shape.py` adds 50 users every 10 s (`RAMP_STEP_USERS`, `RAMP_STEP_SECONDS`, up to `RAMP_MAX_USERS`). After each
step it records the step's numbers and stops at the first broken step: more than 1 % of requests failed (error
status, 503 shed, connection error) or p95 over 1 s.

How to read a row:
- **offered vs req/s**: what the users tried vs what got answered. A big gap without failures means the load
  generator itself could not keep up (check `locust cpu`).
- **p50 / p95 / p99**: what users experienced. p99 rises first when requests start to queue.
- **server p99**: time spent inside the API (from `/traffic.json`). If users see much more than the server, the
  time went into queues before the API (sockets, backlog) or into the load generator.
- **peak**: most requests in flight at once in any second of the last 10 s (the API's limit is compared to this).
- **shed**: requests the API refused at once with 503 (`--max-in-flight`).
- **conns**: TCP connections the API accepted; about one per user means keep-alive works.

## Limits of this setup

- One Locust process holds at most ~1000 connections on this Mac (measured); `ramp.py` runs 4 (`--processes`).
  Then `locust cpu` shows only the coordinating process, and per-step req/s alternates high/low (workers report
  every ~3 s); compare pairs of steps.
- Load generator and API share one Mac (8 cores here): they compete for CPU, and the Mac's own network stack is
  part of what is measured. A second machine (the Pi later) as target gives cleaner numbers.
- Locust measures from the client side with millisecond rounding; its percentiles are approximate (bucketed), the
  API's are exact for the last 10 s.
- Absolute numbers depend on this machine; the comparisons (setting A vs B, own API vs FastAPI, behind a proxy or
  not) are what carry over.

First results and what they taught: [docs/loadtest-2026-10-26.md](../docs/loadtest-2026-10-26.md).
Tests of the ramp logic: `.venv/bin/python -m unittest discover -s loadtest`.
