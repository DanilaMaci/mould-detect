// App wiring: pick a data source (live Supabase or demo), log in if needed, load the selected time range, keep it
// updated in real time, and connect the 3D room, the tiles and the side panel.
import { createDemoSource } from './data/demo.js';
import { glassFog, surfaceRH, ventilationAdvice } from './physics.js';
import { ROOM } from './room-model.js';
import { createRoomScene } from './scene/room.js';
import { ago, clock, fmt } from './ui/format.js';
import { renderTiles } from './ui/hud.js';
import { PANELS } from './ui/panels.js';
import { hoursWhere } from './ui/periods.js';

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;
const RANGES = { '6h': 6 * HOUR, '24h': DAY, '7d': 7 * DAY };
const STALE_AFTER = 3 * MIN;
const REPLAY_MS = 20_000;       // the computer replays the last 24 h in 20 s
const MOULD_RH = 80;
const STAIN_FULL_HOURS = 24;    // visual scale: 24 h above 80 % at the wall in the range = darkest stain

const $ = (sel) => document.querySelector(sel);

const state = {
  range: '24h',
  readings: [],
  weather: [],
  latest: null,
  selected: null,
  connection: 'connecting',
  replay: { active: false },
};
let source;
let scene;
let panelCharts = [];
let pollTimer = null;

async function loadConfig() {
  try {
    return await import('../config.js');
  } catch {
    return {};
  }
}

// ---------- data ----------

const isHourly = () => state.range === '7d';

async function loadRange() {
  const now = Date.now();
  const from = now - RANGES[state.range];
  const [readings, weather] = await Promise.all([
    source.readings(from, { hourly: isHourly() }),
    source.weather(from, now + 2 * DAY),
  ]);
  state.readings = readings;
  state.weather = weather;
  // The newest minute row is the "now" state (window/door, LEDs). Refresh it on every load, so a missed Realtime
  // event cannot leave an old state on screen.
  const recent = isHourly() ? await source.readings(now - 30 * MIN) : readings;
  const last = recent.at(-1);
  if (last && (!state.latest || last.t >= state.latest.t)) state.latest = last;
}

const lastAtOrBefore = (rows, t) => {
  let lo = 0, hi = rows.length - 1, best = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t <= t) { best = rows[mid]; lo = mid + 1; } else hi = mid - 1;
  }
  return best;
};

function weatherNow() {
  return lastAtOrBefore(state.weather, Date.now());
}

/** Hours with the wall surface above 80 % among the given rows. */
function hoursWet(rows) {
  const hourly = isHourly();
  return hoursWhere(rows, (r) => r.wall_temp_c != null && r.rh != null && surfaceRH(r.temp_c, r.rh, r.wall_temp_c) >= MOULD_RH,
    { stepMs: hourly ? HOUR : MIN, maxGapMs: hourly ? 2 * HOUR + 1 : 5 * MIN });
}

function onReading(r) {
  if (state.latest && r.t < state.latest.t) return;   // late duplicate from polling
  state.latest = r;
  if (!isHourly()) {
    state.readings.push(r);
    const from = Date.now() - RANGES[state.range];
    while (state.readings.length && state.readings[0].t < from) state.readings.shift();
  }
  render({ panel: true });
}

async function pollNew() {
  const since = (state.latest?.t ?? Date.now() - 5 * MIN) + 1;
  for (const r of await source.readings(since)) onReading(r);
}

function subscribe() {
  source.subscribe(onReading, (status) => {
    state.connection = status === 'SUBSCRIBED' ? 'live' : 'polling';
    if (state.connection === 'polling' && !pollTimer) {
      // Realtime unavailable: ask for new rows every minute instead
      pollTimer = setInterval(pollNew, MIN);
    }
    renderStatus();
  });
}

// ---------- rendering ----------

function context() {
  const w = weatherNow();
  const latest = state.latest;
  return {
    readings: state.readings,
    weather: state.weather,
    latest,
    weatherNow: w,
    hourly: isHourly(),
    advice: ventilationAdvice({
      indoor: latest && { t: latest.temp_c, rh: latest.rh, co2: latest.co2_ppm },
      outdoor: w && { t: w.temp_c, rh: w.rh },
    }),
  };
}

function renderStatus() {
  const age = state.latest ? Date.now() - state.latest.t : null;
  const stale = age != null && age > STALE_AFTER;
  const dot = $('#live-dot');
  dot.className = `dot ${stale ? 'is-stale' : state.connection === 'live' ? 'is-live' : 'is-polling'}`;
  $('#updated').textContent = age == null ? 'waiting for data…'
    : `${stale ? 'No new data · last' : state.connection === 'live' ? 'Live · updated' : 'Updated'} ${ago(age)}`;
}

function renderPanel() {
  for (const c of panelCharts) c.destroy();
  panelCharts = [];
  const id = state.selected;
  const panel = $('#panel');
  panel.classList.toggle('is-open', Boolean(id));
  panel.setAttribute('aria-hidden', String(!id));
  if (!id) return;
  const hs = ROOM.hotspots[id];
  $('#panel-title').textContent = hs.title;
  $('#panel-subtitle').textContent = hs.subtitle;
  for (const b of document.querySelectorAll('[data-range]')) b.setAttribute('aria-pressed', String(b.dataset.range === state.range));
  const body = $('#panel-body');
  const scroll = body.scrollTop;
  body.innerHTML = '';
  panelCharts = PANELS[id](body, context());
  body.scrollTop = scroll;
}

/**
 * Put one moment into the 3D room: reading l, weather row w, time t (null = live). Live and replay share this.
 * Hourly rows hold fractions for window/door (any opening in the hour counts as open).
 */
function updateScene(l, w, t, rows = state.readings) {
  scene.setTime(t);
  scene.setIndoor(l);
  scene.setWeather(w);
  const advice = ventilationAdvice({
    indoor: l && { t: l.temp_c, rh: l.rh, co2: l.co2_ppm },
    outdoor: w && { t: w.temp_c, rh: w.rh },
  });
  scene.setAdvice(advice.action);   // LED on the room node lights up when airing is advised
  const wallRh = l?.wall_temp_c != null ? surfaceRH(l.temp_c, l.rh, l.wall_temp_c) : null;
  // Window/door buttons and the wall probe drive the 3D room (null = unknown: closed window, open door)
  scene.setStates({ windowOpen: l?.window_open > 0, doorOpen: !(l?.door_open != null && l.door_open < 1),
    known: l?.window_open != null });
  scene.setWall({ surfaceRh: wallRh });
  const outT = l?.outdoor_temp_c ?? w?.temp_c;
  scene.setGlass({ fog: l && outT != null ? glassFog(l.temp_c, l.rh, outT) : 0 });
  const upTo = t == null ? rows : rows.filter((r) => r.t <= t);
  scene.setStain(hoursWet(upTo) / STAIN_FULL_HOURS);
  scene.setTagValues({
    climate: l ? `${fmt(l.temp_c, 1, '°C')} · ${fmt(l.rh, 0, '%')}` : '–',
    co2: l ? fmt(l.co2_ppm, 0, 'ppm') : '–',
    outdoor: outT != null ? `${fmt(outT, 1, '°C')}${w ? ` · ${fmt(w.rh, 0, '%')}` : ''}` : '–',
    wall: l?.wall_temp_c != null ? `${fmt(l.wall_temp_c, 1, '°C')} · ${fmt(wallRh, 0, '%')} at surface` : 'probe not reporting',
  });
}

function render({ panel = false } = {}) {
  const ctx = context();
  renderTiles($('#tiles'), ctx);
  renderStatus();
  if (!state.replay.active) updateScene(ctx.latest, ctx.weatherNow, null);
  if (panel) renderPanel();
}

// ---------- replay on the desk computer: the last 24 h played through the 3D room ----------

const ZOOM_MS = 1400;   // the camera's flight to the monitor

async function startComputerReplay() {
  if (state.replay.active) return;
  state.replay = { active: true };
  if (state.selected) select(null);
  const now = Date.now();
  const [rows, weather] = await Promise.all([source.readings(now - DAY), source.weather(now - DAY - HOUR, now)]);
  if (!state.replay.active) return;   // stopped while loading
  if (!rows.length) { stopComputerReplay(); return; }
  scene.enterComputer();
  const [t0, t1] = [rows[0].t, rows.at(-1).t];
  const startAt = performance.now() + ZOOM_MS;
  const step = (nowMs) => {
    if (!state.replay.active) return;
    const k = Math.min(1, Math.max(0, (nowMs - startAt) / REPLAY_MS));
    const t = t0 + k * (t1 - t0);
    updateScene(lastAtOrBefore(rows, t), lastAtOrBefore(weather, t), t, rows);
    scene.setComputerClock(`${new Date(t).toLocaleDateString([], { weekday: 'short' })} ${clock(t)}`, k);
    if (k < 1) requestAnimationFrame(step);
    else setTimeout(stopComputerReplay, 800);
  };
  requestAnimationFrame(step);
}

function stopComputerReplay() {
  if (!state.replay.active) return;
  state.replay = { active: false };
  scene.exitComputer();
  render();   // back to the live state
}

function select(id) {
  state.selected = id;
  scene.select(id);
  renderPanel();
}

// ---------- login ----------

function login() {
  const overlay = $('#login');
  overlay.hidden = false;
  return new Promise((resolve) => {
    $('#login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const error = $('#login-error');
      error.textContent = '';
      try {
        await source.signIn($('#login-email').value, $('#login-password').value);
        overlay.hidden = true;
        resolve();
      } catch (err) {
        error.textContent = err.message || 'Sign-in failed';
      }
    });
  });
}

// ---------- boot ----------

async function boot() {
  const config = await loadConfig();
  const params = new URLSearchParams(location.search);
  const demo = params.has('demo') || (!config.SUPABASE_URL && !config.API_URL);
  // The own API (services/api) when config.js names one; ?supabase switches back to Supabase
  const useApi = !demo && Boolean(config.API_URL) && !params.has('supabase');
  if (demo) {
    source = createDemoSource();
  } else if (useApi) {
    const { createApiSource } = await import('./data/api.js');
    source = createApiSource({ baseUrl: config.API_URL, readToken: config.API_READ_TOKEN, deviceId: ROOM.devices.room });
  } else {
    const { createSupabaseSource } = await import('./data/supabase.js');
    source = createSupabaseSource({ url: config.SUPABASE_URL, publishableKey: config.SUPABASE_PUBLISHABLE_KEY,
      deviceId: ROOM.devices.room });
  }
  const badge = $('#source-badge');
  badge.textContent = demo ? 'Demo data' : useApi ? 'Live · own API' : 'Live · Supabase';
  badge.classList.toggle('is-demo', demo);
  $('#room-name').textContent = ROOM.name;

  // Sun path: the location comes from config.js (rounded coordinates are enough); demo uses a neutral default
  const sunLocation = Number.isFinite(config.LATITUDE) && Number.isFinite(config.LONGITUDE) && !demo
    ? { lat: config.LATITUDE, lon: config.LONGITUDE } : undefined;
  scene = createRoomScene($('#scene'), { onSelect: select, location: sunLocation,
    onComputer: (action) => (action === 'start' ? startComputerReplay() : stopComputerReplay()) });

  $('#tiles').addEventListener('click', (e) => {
    const t = e.target.closest('[data-open]');
    if (t) select(t.dataset.open);
  });
  $('#panel-close').addEventListener('click', () => select(null));
  document.addEventListener('keydown', (e) => {
    if (e.target.closest?.('input, textarea')) return;
    if (e.key === 'Escape') {
      if (state.replay.active) stopComputerReplay();
      else if (state.selected) select(null);
    } else if (e.key === 'r' || e.key === 'R') {
      startComputerReplay();   // keyboard route to the replay (the monitor needs a pointer)
    }
  });
  for (const b of document.querySelectorAll('[data-range]')) {
    b.addEventListener('click', async () => {
      state.range = b.dataset.range;
      if (state.replay.active) stopComputerReplay();
      await loadRange();
      render({ panel: true });
    });
  }
  if (!demo) {
    const out = $('#sign-out');
    out.hidden = false;
    out.addEventListener('click', async () => { await source.signOut(); location.reload(); });
  }

  if (await source.needsLogin()) await login();

  try {
    await loadRange();
  } catch (err) {
    $('#updated').textContent = `Could not load data: ${err.message}`;
    throw err;
  }
  render({ panel: true });
  subscribe();
  setInterval(renderStatus, 1000);
  // Safety net: if nothing arrived for a while (Realtime hiccup), ask for new rows
  setInterval(() => { if (state.latest && Date.now() - state.latest.t > STALE_AFTER) pollNew(); }, MIN);
  setInterval(async () => { await loadRange(); render({ panel: true }); }, 15 * MIN);   // weather updates hourly
}

boot().catch((err) => {
  console.error(err);
  window.showStartupError?.(err.message || String(err));
});
