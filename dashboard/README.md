# Dashboard

A light, static website: a 3D cutaway of the room (floor and the two outside walls) with live tags on the sensors,
weather outside the French doors, room air that tints with CO₂ and humidity, and click-through panels with charts.

- **No build step, no installs.** Plain ES modules; three.js, uPlot and supabase-js load from jsDelivr at pinned
  versions (see `index.html` and the imports).
- **Two data sources, one interface** (`src/data/`): live Supabase with Realtime updates, or synthetic demo data.
  Without `config.js` the site runs in demo mode, so a public deployment never shows the real house.
- **The room reacts to the sensors:** the side windows swing open and cool air flows in when the window button is
  on; the door symbol on the floor swings with the door button; the room node's red/yellow LEDs mirror the real
  ones; a patch around the wall probe turns green, amber or red with the humidity at the wall surface.
- **Honest charts:** times without data are bridged with a dashed line (no invented values); shaded bands mark
  window-open and door-closed periods.
- **Replay on the desk computer:** click the monitor (or press R) and the camera zooms in; the screen shows the
  room from the overview camera while the last 24 h play in 20 s (windows, door, CO₂ haze, wall colour, fogged
  glass, heating, sun), then zooms back out. A click or Esc stops it.
- **Click to play:** click the door or a side window to open/close it (the next real reading puts the measured
  state back); each click on the glass adds fog, which fades when you stop; the radiator heats up for ~12 s; the
  couch "adds people" and the CO₂ haze thickens, then clears.
- **More physics on screen:** the balcony glass mists up when its inside surface nears the dew point (glass
  temperature from a double-glazing U-value, assumed); a mould stain darkens around the wall probe with the hours
  the wall spent above 80 % humidity in the shown range (a visual scale, not a mould-growth model); the radiator
  glows and warm air rises during the heating schedule; the sun follows the real time (`src/sun.js`, NOAA
  equations) for `LATITUDE`/`LONGITUDE` in `config.js` (rounded; demo uses a neutral default).

## Run locally

```bash
cd dashboard
python3 serve.py                 # then open http://localhost:8000  (demo mode)
```

A web server is needed because browsers block ES modules from `file://`. `serve.py` is Python's built-in server
with caching switched off: with plain `python3 -m http.server` the browser can keep running old copies of the
scripts after an update (hard reload with Cmd+Shift+R fixes that).

While it runs, `serve.py` also keeps `weather_hourly` complete: at start-up and then every hour it runs the weather
sync (`jobs/fetch_weather.py --sync`), which finds missing hours (up to 92 days back, Open-Meteo's limit), fetches
them plus the 2-day forecast, and prints the coverage. It needs `LATITUDE`, `LONGITUDE`, `SUPABASE_URL` and
`SUPABASE_SECRET_KEY` in the repository's `.env`; without them it prints a note and only serves.
`python3 serve.py --no-weather` serves only.

## Live data

1. Apply `supabase/migrations/20261022030000_dashboard_read_access.sql` in the Supabase SQL Editor (and later
   migrations, e.g. `20261022050000_hourly_view_probes_states.sql` for the 7-day view of the probes and buttons).
2. Supabase → Authentication → Users → **Add user** (email + password, auto-confirm).
3. Allow that user to read the data (SQL Editor):
   ```sql
   insert into public.dashboard_viewers (user_id) select id from auth.users where email = '<your email>';
   ```
4. Recommended: Authentication → Sign In / Providers → turn off **Allow new users to sign up**. Not required for
   privacy (only listed viewers can read), but nobody else needs an account.
5. `cp config.example.js config.js` and fill in the project URL and the **publishable** key (never the secret key).
   `config.js` is gitignored.
6. Reload and sign in. `?demo` in the URL forces demo mode.

Own API instead of Supabase (services/api): add `API_URL` and `API_READ_TOKEN` to `config.js` (see
`config.example.js`); the badge then says "Live · own API", `?supabase` switches back. New rows arrive by polling
every 15 s instead of Supabase Realtime.

## Layout

| Path | Contents |
|---|---|
| `index.html`, `styles.css` | Page, design tokens (light + dark), layout for desktop and phones |
| `src/main.js` | Wiring: data source, login, time ranges, Realtime with polling fallback, rendering |
| `src/room-model.js` | The room as data: size, openings, devices, hotspots and camera views. Add sensors here |
| `src/scene/room.js` | three.js scene built from the room model |
| `src/data/supabase.js`, `src/data/demo.js` | Live and synthetic data sources (same interface) |
| `src/physics.js` | Dew point, absolute humidity, surface humidity, glass temperature and fog, ventilation advice |
| `src/sun.js` | Sun elevation/azimuth (NOAA) and its direction in the scene |
| `src/ui/` | Tiles, side-panel content, uPlot charts, formatting |
| `tests/` | `npm test` (Node's built-in test runner; physics against reference values, demo data plausibility, room layout, chart periods and gaps) |

## Deploy

Any static host (GitHub Pages, Netlify, Cloudflare Pages) serving this folder. Without `config.js` it shows demo
data. With `config.js` it shows live data to signed-in viewers only.

**Cloudflare Pages from the Git repository** (recommended): Workers & Pages → Create → Pages → connect the GitHub
repository; framework preset *None*, build command empty, build output directory `dashboard`. Every push to `main`
redeploys. Only committed files are served, so the gitignored `config.js` never reaches the site and it runs in demo
mode. A custom domain such as `mould.<your-domain>` is added under the project's *Custom domains* tab.

Do not upload this folder from your own computer (`wrangler pages deploy dashboard`, or drag-and-drop) while
`config.js` exists: direct uploads include every file in the folder, gitignored or not, and `config.js` holds the
API read token and the location.
