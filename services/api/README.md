# services/api

A small HTTP API for the sensor readings, written with Python's standard library only, so every part of what a
web framework normally hides is visible: routing, parsing, validation, authentication, limits, metrics. It is the
"own" side of the platform-track comparison; a FastAPI twin with the same endpoints comes later, and both are
load-tested.

```
ESP32 / load test ──POST /api/readings──▶  api.py  ──▶ SQLite (data/api.sqlite)
dashboard (api.js) ──GET /api/readings──▶     │
Prometheus / you ──────GET /metrics────▶      └── /traffic: live requests/s, errors, latency
```

## Run it

```sh
# 1. tokens (once): add to .env
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # run twice: one per line below
#    API_DEVICE_TOKENS=node1=<first token>
#    API_READ_TOKEN=<second token>

# 2. real history from Supabase into the API's database (read-only on Supabase; run again to catch up)
python3 services/api/import_supabase.py

# 3. start
python3 services/api/api.py          # http://127.0.0.1:8200/traffic
```

The 3D dashboard can read from it: in `dashboard/config.js` set `API_URL = 'http://127.0.0.1:8200'` and
`API_READ_TOKEN`, start `dashboard/serve.py`, open http://localhost:8000 (badge "Live · own API"; `?supabase`
switches back). The ESP32 keeps posting to Supabase.

Tests: `python3 -m unittest discover -s services/api` (40 tests, real HTTP on a free local port). Load test:
[loadtest/README.md](../../loadtest/README.md).

## Endpoints

| Method + path | Token | Answer |
|---|---|---|
| `GET /api/health` | none | `{"status": "ok", "readings": n}` |
| `POST /api/readings` | device | 201 `{"id": n}`; the same JSON the ESP32 sends to Supabase |
| `GET /api/readings` | read | rows; `?device_id=&since=&until=&limit=` (ISO times, limit ≤ 5000), `&hourly=1` for hourly averages |
| `GET /api/weather` | read | weather hours; `?since=&until=&limit=` |
| `GET /metrics` | none | Prometheus text format |
| `GET /traffic` | none | live traffic page (and `/traffic.json`) |

Errors are JSON `{"error": ..., "problems": [...]}`: 400 bad JSON, 401 token, 411 no Content-Length, 413 body over
4 KB, 415 not JSON, 422 invalid values (all problems listed), 503 busy (with `Retry-After`).

## How it works

- **One thread per connection** (`ThreadingHTTPServer`), HTTP/1.1 keep-alive so clients reuse connections, a
  10 s socket timeout so idle or slow clients cannot hold threads for ever, listen backlog 128.
- **Load shedding:** at most `--max-in-flight` (400) requests are handled at once; the next one gets 503 at once,
  and its small body is read so the connection stays open (closing it made clients reconnect, which added load
  exactly when there was too much). Without a limit, every extra request queues, latency grows for everybody, and
  clients time out anyway. 400 comes from the load test: requests arrive in clumps, so the per-second peak in flight
  is 10–50x the average (~350 at 2000 req/s while still fast, ~650 in the meltdown above); the first default, 64,
  refused work from ~130 req/s (docs/loadtest-2026-10-26.md).
- **SQLite in WAL mode**, one connection per thread. Readers do not block; writers take turns. A writer waiting more
  than 5 s gets 503.
- **Validation** (`validate.py`) mirrors the Supabase table's CHECK constraints, so both backends accept the same
  rows. Unknown fields are refused, types are strict (Python treats `True` as `1` — refused for numbers and vice
  versa), NaN/Infinity are refused (Python's JSON parser accepts them by default), device time must be within
  5 min ahead / 7 days behind.
- **Metrics** (`metrics.py`): Prometheus counters and a latency histogram for `/metrics`; a 60-second rolling window
  with exact percentiles and the per-second peak in flight for `/traffic`. Labels use fixed route names, never raw
  paths. TCP connections are counted (requests per connection shows whether keep-alive works). A client that
  disconnects mid-request is counted as 499 (nginx's "client closed request"), so 500 always means a bug here.

## Security choices (for the review)

- **Device id from the token**, not from the body: a node's token can only write that node's rows (Supabase's
  current insert policy accepts any row from anyone holding the public key).
- **Separate tokens for writing and reading:** a stolen device token cannot read the history; the dashboard's read
  token cannot write. Tokens shorter than 16 characters are refused at start-up; comparisons are constant-time.
- **Fail closed:** without `API_DEVICE_TOKENS` every POST is refused; without `API_READ_TOKEN` every read is.
- **Header tokens, not cookies:** browsers never attach them on their own, so cross-site request forgery does not
  apply (unlike the monitor's page buttons). Cross-origin reads are allowed only for the origins in
  `API_CORS_ORIGINS` (default: the dashboard on localhost:8000).
- **Limits:** 4 KB bodies, Content-Length required (no chunked bodies), 5000 rows per query, 10 s timeouts.
- **Little information leaked:** `Server: mould-api` instead of the Python version; 500s say "internal error"
  (details only in the terminal).
- Listens on 127.0.0.1 only. Not yet: TLS (the proxy's job), per-client rate limits (proxy), token rotation,
  request logs to a file.

## Limits

- Python threads take turns on the interpreter lock (GIL) for Python code, so CPU-heavy work does not get faster
  with more threads; this API mostly waits on sockets and SQLite, where threads help. Part of what the load tests
  will show.
- Metrics live in memory and reset on restart (Prometheus keeps the history).
- The importer copies; it does not keep the API in sync on its own. Load tests must use their own database file
  (`--db`), or their rows mix with the real ones.
