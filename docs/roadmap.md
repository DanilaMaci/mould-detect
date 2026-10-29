# Roadmap

Order chosen so that each step produces something usable and testable before the next one depends on it. Heating
season (October–March) is when condensation and mould risk occur, so the full sensor set should be logging by
December to have training data.

| # | Step | Done when |
|---|---|---|
| 1 | Export the existing BME280 data to `data/`; exploration notebook (gaps, sampling, noise, daily pattern, dew point) | plots and a list of data-quality issues |
| 2 | Parts list and placement in `docs/hardware.md`; decide which node measures what | table filled in |
| 3 | `analysis/` package: psychrometrics, surface RH, fRsi, mould index, with tests against reference values | `pytest` passes |
| 4 | Schema v2 migration: `devices`, multi-sensor readings, `window_events`; move existing rows | migration applied, old data queryable |
| 5 | Room node v2: wall and outdoor probes, CO2, SNTP timestamps, batching with an offline backlog | a day of complete rows |
| 6 | Window nodes + gateway (deep sleep, reed switch wake, ESP-NOW) | open/close events arrive within seconds |
| 7 | Dashboard (static 3D site in `dashboard/`, first version 2026-10-22) and a scheduled risk job with notifications | risk visible and updating |
| 8 | Forecasting (from ~December): time-based splits, persistence and physics baselines, then gradient boosting | model beats baselines on held-out weeks |
| 9 | Ventilation advice: when to open which window and for how long | advice logged and checked against outcomes |
| 10 | Public release: README results, synthetic example data, release checks | checks passed |

## Status (2026-10-29)

Done: step 2; step 4 partly (new columns on the one readings table, no `devices` or `window_events` tables yet);
step 5 partly (CO₂, wall and outdoor probes; SNTP and offline backlog open); step 7 partly (dashboard with probes,
surface humidity, window/door bands and replay; the scheduled risk job is open). Window and door state comes
from two buttons with LEDs on the room node (lit = open) until wired contacts are installed.

## Next

- Calibration: salt-jar test (saturated NaCl holds about 75 % RH) to choose between the BME280 and SCD-40 humidity;
  ice-bath check of both temperature probes (both should read 0.0 °C)
- Window contacts wired to the room node (GPIO25–33, internal pull-up), state per opening in Supabase and on the 3D
  doors/windows
- **Advice LED on the room node** (GPIO23, already drawn in the 3D model), lit when airing is advised. Open design
  choice: compute it on the device (CO₂, RH and outdoor absolute humidity read from Supabase), or have a scheduled
  job write the advice to a one-row table the node reads (needs a narrow read grant for the device key)
- Weather: hourly GitHub Actions sync added (2026-10-29); still to do: store forecast snapshots as issued, so a later
  forecast evaluation cannot peek at revised data
- Firmware: SNTP timestamps, 1-minute averages, offline backlog, heartbeat
- Data export, first exploration notebook (step 1), Python `mould` package with tests (step 3)
- Window nodes (XIAO, ESP-NOW) only if openings in other rooms are added; this room's are wired

## Platform track (learning, 2026-10-26)

Built on the Mac first, moved to a Raspberry Pi later (not bought yet). The ESP32 keeps posting to Supabase until
the Pi runs 24/7, so data collection is never at risk.

- [x] `services/api` (2026-10-26): stdlib API: health, token-protected + validated `POST /api/readings` into SQLite
      (device id from the token), `GET /api/readings` (+ hourly) and `/api/weather` with a read token, load shedding,
      `/metrics` (Prometheus), live `/traffic` page, Supabase importer, dashboard source `api.js`. Later:
      store-and-forward to Supabase, FastAPI twin
- [x] Load test (2026-10-26, `loadtest/`, Locust in .venv): ramp until it breaks; own API ≈ 2000 req/s on the Mac,
      findings in docs/loadtest-2026-10-26.md
- [ ] Monitor v2 (history, graphs) and Prometheus + Grafana (Docker) — the rest of the platform track (proxy, FastAPI
      twin, comparison) continues in a separate project, an API comparison playground (2026-10-26)
- [ ] `services/proxy`: mini reverse proxy ("mini nginx"): routing (`/api/` → API, rest → dashboard files), access
      log, X-Forwarded-For, timeouts, 502/413, per-IP rate limit; then the same in a real nginx.conf to compare
- [x] `services/monitor` (2026-10-26): node silent, sensor ranges / stuck values / lost probe, unexpected device ids,
      weather gaps + freshness, HTTP targets; state + history in SQLite, debounced ntfy alerts on change with an
      outbox, status page with explanations and controls (run now, test, mute, pause). Not yet run on the real data
- [ ] Pi: the three services + weather sync as systemd units, Cloudflare Tunnel, SSD, backups

## Ideas to make it stand out

- [partly done 2026-10-22: stain from hours above 80 %; VTT model still open] **Mould index over time** (VTT model) computed hourly and painted onto the 3D wall where the probe is: the wall
  slowly "stains" as risk accumulates and recovers in dry spells
- **Forecast with honest evaluation**: predict wall-surface RH 6–12 h ahead from the weather forecast; show it as a
  dashed line, and publish a small evaluation page (persistence and physics baselines, time-based splits, error by
  horizon). This is what makes the ML credible to a reviewer
- **Ventilation effectiveness**: air-change rate from the CO₂ decay after each opening ("10 min of airing removed
  X g of water"), one point per opening on a chart
- **Smart airing**: trade moisture removed against heat lost, recommend the shortest airing that does the job
- **Notifications** (ntfy or Telegram) when airing is advised, plus the physical LED
- **Public demo on GitHub Pages** (demo mode is built in) with a GIF of the 3D room at the top of the README,
  a Mermaid architecture diagram, and CI badges (C host tests, Node tests, Python tests)
- **Diary on the dashboard** (once live): one-tap events the sensors cannot see — laundry on, someone home sick,
  guests, away, heating changed — stored in a Supabase table and drawn as markers on the charts; useful labels
  for explaining spikes and for the model
- **Data-quality panel**: uptime, Wi-Fi RSSI, gaps, sensor disagreement
- **Psychrometric chart** panel with the room's state plotted live
- **Enclosure** for the nodes designed and printed on the 3D printer, rendered in the README
- **Robot tie-in**: use the LiDAR robot's scan to build the room model and place the sensors automatically
- **Write-up after the winter**: what the data showed about the room, with the evaluation numbers
