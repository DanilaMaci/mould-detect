# services/monitor

Watches the real data pipeline (ESP32 → Supabase → weather sync) and tells you when something breaks: a node that
stopped sending, a sensor that reads nonsense or froze, a probe that fell off, holes in the weather table, a local
service that is down. It keeps every check's state in SQLite, pushes a phone notification (ntfy) when a check
changes state, and serves a status page on this Mac where you can see everything and control the monitor.

Python 3.11+, standard library only (like `jobs/` and `dashboard/serve.py`).

## Run it

```sh
cp .env.example .env              # if not done yet; fill in SUPABASE_URL and SUPABASE_SECRET_KEY
python3 services/monitor/monitor.py           # every 60 s; page at http://127.0.0.1:8100
python3 services/monitor/monitor.py --once    # one run, print every result, exit 1 if anything fails
```

Optional settings in `.env`:

| Setting | Meaning | Default |
|---|---|---|
| `MONITOR_DEVICES` | node ids that must be sending, comma-separated | `node1` |
| `NTFY_TOPIC` | ntfy topic for alerts; empty = alerts only printed | empty |
| `NTFY_SERVER` | ntfy server (self-hosted later) | `https://ntfy.sh` |
| `NTFY_TOKEN` | access token, for a server with access control | empty |
| `MONITOR_HTTP` | local services to check, `name=url,name=url` | empty |

Phone setup: install the ntfy app, make a long random topic name
(`python3 -c 'import secrets; print(secrets.token_urlsafe(18))'`), subscribe to it in the app, put it in `.env` as
`NTFY_TOPIC`, start the monitor, press **Send test notification** on the page.

Example `MONITOR_HTTP=dashboard=http://localhost:8000/` checks that `serve.py` is up; the API and proxy are added the
same way once they exist.

Tests: `python3 -m unittest discover -s services/monitor` (no network: Supabase and ntfy are faked; the page tests
use a real local port).

## The status page

`http://127.0.0.1:8100` — refreshes every 30 s.

- **Checks table**: status, detail, since when, and per check **Mute 1 h / 24 h** (or Unmute). Click a check's name
  for what it watches, the exact rule with the current thresholds, and what to do when it fails.
- **Buttons**: **Run checks now** (wakes the loop, shows the result at once), **Send test notification**,
  **Pause alerts 1 h / 24 h** (or Resume) — e.g. while you rewire the breadboard.
- **Recent changes**: the last 30 state changes and what happened to each alert (sent, queued, muted, paused).
- **How the monitor works** and **Settings** (the topic itself is never shown).
- `/status.json` the same data for scripts; `/healthz` answers 200 while runs are recent, 503 when the monitor
  has stalled (for an outside uptime check later).

## What it checks

| Check | Rule | Why |
|---|---|---|
| `node1/silent` | warn at 5 min without a row, fail at 15 min | the node posts every minute |
| `node1/ranges` | newest values outside plausible limits → fail (e.g. RH 100 %, wall 85 °C) | sensor/wiring fault, not weather |
| `node1/stuck` | a BME280/SCD-40 column with one single value for 30 min → warn (DS18B20 probes not judged: a heated wall can hold one 0.0625 °C step all night) | frozen bus or re-sent value; real sensors jitter |
| `node1/scd40`, `node1/wall_probe`, `node1/outdoor_probe` | no value for 10 min while the node sends → fail; none in 30 days → off | a probe fell off vs. never fitted |
| `devices/unexpected` | rows from ids not in `MONITOR_DEVICES` in the last 30 min → warn (ids shown cut to 32 safe characters) | wrong DEVICE_ID, or someone using the public insert key |
| `weather/gaps` | any missing hour in the last 72 h → warn | the model needs every hour |
| `weather/fresh` | last sync older than 3 h → warn | the sync runs only while `serve.py` runs |
| `supabase` | any query failing → fail | without it nothing else can be judged |
| `http/<name>` | no answer in 5 s or HTTP ≥ 400 → fail | local services |

Thresholds are constants at the top of `checks.py`; the page's explanations are generated from the same constants.

## How it works

```
every 60 s (or "Run checks now")
  gather()   ~7 small read-only PostgREST queries + HTTP GETs    -> Snapshot      monitor.py
  evaluate() pure rules, no I/O                                   -> [Result]      checks.py
  update()   debounce, commit changes, queue alerts               -> SQLite        store.py
  deliver()  queued alerts -> ntfy (skip muted/paused)                             monitor.py
status page thread: reads SQLite, buttons write mutes/pause or wake the loop        monitor.py
```

**Statuses.** ok, off (sensor never fitted), warn, fail, unknown. Unknown means "nothing to judge": Supabase is not
answering, or the node is silent so its sensor checks have no fresh data.

**Debounce.** A new status counts only after 2 runs in a row agree. One odd sample does not wake you up; the price is
up to one extra minute before an alert. The page shows a pending change as "(fail? 1/2)". After a gap (monitor
stopped, Mac asleep: more than 3 intervals) a pending change starts counting again.

**Alerts on change, by severity.** ok/off = 0, warn = 1, fail = 2. An alert goes out when a committed status has a
different severity than the last *known* status. Unknown never alerts by itself, so ok → unknown → fail alerts once
(for the fail), and fail → unknown → fail does not alert again.

**One cause, one alert.** A silent node fails `silent` and turns its sensor checks unknown; Supabase down fails
`supabase` and turns every data check unknown. Without this, one outage would send six notifications.

**Outbox.** Alerts are rows in SQLite until ntfy accepts them, sent in order, retried every run for 24 h. A network
outage delays alerts; it does not lose or reorder them. An alert ntfy rejects for good (HTTP 4xx other than 408/429)
is marked failed so it cannot block the rest. An alert raised while its check is muted or all alerts are paused is
marked as such and never sent later; muting a check also stops its alerts that are still queued.

**State survives restarts** (`data/monitor.sqlite`, gitignored like all house data): restarting the monitor does
not re-send alerts.

## Choices and trade-offs

**Polling instead of push.** Supabase could push each new row (Realtime, database webhooks), which would catch a bad
value within seconds. But the most important failure is *silence*, and the absence of an event never triggers a
push: something with a clock has to notice it. Polling every minute covers both with one mechanism; the cost is up
to a minute of delay and ~10 small queries per minute (≈14 000/day, far inside Supabase's free tier).

**Own code instead of Uptime Kuma or Prometheus + Alertmanager + Grafana.**
- Uptime Kuma is excellent at "is this URL up" and heartbeat ("push") monitors, but cannot express "wall_temp_c has
  been null for 10 minutes while the node keeps sending" or "a value has not changed for 30 minutes".
- Prometheus would need an exporter that turns the database into metrics (most of this code anyway), plus three more
  services to run and secure. It brings history graphs and a query language this project does not need yet.
- Own code (~950 lines including the page and the explanations) is exactly the rules this pipeline needs, and every rule is unit-tested. The
  costs: my own bugs (mitigated by tests that were checked by planting bugs), no graphs, and nothing else watches the
  monitor (see limits). A `/metrics` endpoint in Prometheus format can be added later if a Grafana setup appears.

**Debounce + state changes instead of alerting on every bad sample.** Fewer, more meaningful alerts at the price of
~1 minute latency. No repeated reminders while something stays broken: the page shows it, the phone said it once.

**Controls on the page, settings in `.env`.** Mute, pause, run-now and test are on the page because you need them in
the moment. Thresholds and targets stay in code / `.env`: editing them from a web form would add an input surface
to secure and a second source of truth.

## Security notes (for the review later)

- **Read-only use of a write-everything key.** The monitor only reads, but `SUPABASE_SECRET_KEY` bypasses row level
  security and could write anything. Better: a dedicated read-only Postgres role and key. The key travels only in a
  request header, which no error text includes; anything URL-like is cut out of error texts (urllib puts whole URLs,
  ntfy topic included, into some messages), and `SUPABASE_URL` / `NTFY_SERVER` must start with http(s):// (tested).
  The page's Settings table shows the Supabase project URL (not secret, but it is your project's address).
- **ntfy.sh topics are public by name.** Anyone who guesses the topic can read and send. Use a long random topic; the
  page never shows it; messages contain check names and short details only. Self-hosted ntfy with a token
  (`NTFY_SERVER`, `NTFY_TOKEN`) removes that exposure.
- **The page only listens on 127.0.0.1.** Other devices on the Wi-Fi cannot reach it.
- **CSRF.** Any website open in your browser can make it POST to `127.0.0.1:8100`. Every button carries a random
  token (new at each start) that such a site cannot read; POSTs without it get 403 (tested).
- **DNS rebinding.** A site could point its own domain at 127.0.0.1 to read the page (and the token) as "same
  origin". Requests whose Host header is not `127.0.0.1:port` or `localhost:port` get 421 (tested).
- **Stored XSS.** Device ids come from rows anyone holding the public insert key can write. Everything from the
  database is HTML-escaped, and the Content-Security-Policy allows no scripts at all (tested with a `<script>` id).
- **Clickjacking.** `frame-ancestors 'none'`: no other page can frame the buttons.
- **Input validation.** Button values are checked against fixed lists (known check ids, 1 or 24 h); bodies over
  2 KB or with a bad length are refused, slow clients time out after 10 s, a locked database answers 503 (tested).
  The page only shows fixed messages after a button; nothing from the request is echoed back. Device ids in
  `MONITOR_DEVICES` must be plain ASCII (they end up in notification titles).
- **Row floods.** Anyone with the public insert key can add rows. The node's window is fetched newest first per
  node, so a flood under its id or another id cannot push the newest real row out of Supabase's 1000-row answers.

## Limits

- Runs only while this Mac is awake and the terminal is open. Nothing watches the watcher: an outside service
  pinging `/healthz` (or a heartbeat to healthchecks.io) would, once it runs on the Pi.
- Silence compares this machine's clock with Supabase's `received_at`. macOS keeps its clock synced, so this is
  fine on the Mac; a Raspberry Pi has no battery clock and must have synced (NTP) before the monitor starts.
- Silence is judged on `received_at` of the newest row by `measured_at`; once the firmware sends a backlog with
  device timestamps (stage 7) this may need `received_at` ordering.
- The probe "lost vs. never fitted" lookback queries 30 days every run for a probe that was never fitted; cheap now,
  worth caching if the table grows a lot.
- One threshold set for every node; per-node settings when there is more than one node.
