# Architecture

## Data flow

Target design. Built so far: step 1 for the room node, step 2 for readings and weather, and the dashboard in
step 4 (it computes the derived quantities in the browser, `dashboard/src/physics.js`). Planned: window nodes,
window events, the Python analysis job and ventilation notifications.

1. **Nodes measure.** The room node reads its sensors every minute and posts one JSON row over HTTPS to the Supabase
   REST API. Planned: window nodes that sleep and send only when a window opens or closes.
2. **Postgres stores.** One row per node per sample in a readings table (planned: window changes as events in a
   separate table). CHECK constraints reject impossible values; the device key can insert but not read (Postgres
   row-level security, RLS).
3. **Python analyses (planned).** A scheduled job pulls new rows, computes the derived quantities below, updates the
   mould index and the forecast, and writes the results back to their own tables.
4. **Outputs.** A dashboard reads the readings (later also the result tables); planned: a notification says when
   ventilating would help.

## Derived quantities

| Quantity | From | Why it matters |
|---|---|---|
| Dew point | indoor T, RH | Temperature at which room air condenses |
| Absolute humidity (g/m³), indoor and outdoor | T, RH | Ventilating dries the room only if outdoor air holds less water than indoor air |
| Surface RH at the wall | indoor vapour pressure, wall T | The humidity mould actually experiences |
| Temperature factor `fRsi = (T_wall − T_out) / (T_in − T_out)` (building-physics term for the inside surface) | wall, indoor, outdoor T | One number for how cold the wall gets relative to the weather; describes the wall, not the weather |
| Air-change rate after opening a window | CO2 decay | How effective each ventilation is |
| Mould index (e.g. VTT model) | surface T and RH over time | Risk accumulates with time at high surface humidity and declines in dry periods |

Equations, constants and sources go into `docs/physics.md` when the analysis package is written.

## Storage estimate

5 nodes × 1 sample/min ≈ 2.6 million rows a year. At roughly 100 bytes per row including the index, that is
about 260 MB a year, inside the Supabase free tier (500 MB) for well over a year. Hourly roll-ups and Parquet
archives of old raw data extend this.

## Outdoor weather

Outdoor humidity, temperature and forecasts come from the Open-Meteo API, fetched by the scheduled Python job
into its own table `weather_hourly` (one row per hour, upserted, so every run also repairs the last two days and
missed runs leave no gap); `--past-days` (up to 92) backfills. The house location is a private setting
(`.env`, rounded to about 1 km), never in the repository. The balcony probe stays as the local ground truth for
outdoor temperature.

## Open design decisions

- Window nodes: ESP-NOW to a gateway (battery-friendly) or direct Wi-Fi
- Device timestamps: SNTP on each node, or arrival time at the gateway or database
- Scheduler: GitHub Actions cron or Supabase pg_cron + Edge Function
