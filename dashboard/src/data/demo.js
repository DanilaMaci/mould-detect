// Synthetic data with the same shape as the Supabase source: used for the public demo and for development.
// Nothing here comes from the real house. A small physical model (air changes, CO2 and moisture from occupants,
// airing twice a day) keeps the numbers plausible and internally consistent.
import { absoluteHumidity, dewPoint, rhFromAbsolute } from '../physics.js';

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

const VOLUME = 120;          // m³: room plus the hallway it shares air with (door usually open)
const ACH_CLOSED = 0.4;      // air changes per hour, windows closed
const ACH_AIRING = 6;        // windows wide open
const CO2_OUTDOOR = 420;     // ppm
const CO2_PER_PERSON = 0.3;  // L/min exhaled CO2, resting adult
const WATER_PER_PERSON = 50; // g/h breathing and skin
const AIRING = [[8, 0], [19, 30]];   // window-open times (h, min), 10 minutes each
const DOOR_CLOSED = [22, 30];       // the room door is shut for 30 minutes each evening
const WALL_FRSI = 0.7;             // temperature factor of the cold wall spot: (T_wall - T_out) / (T_in - T_out)
const WALL_LAG_MIN = 6 * 60;       // the wall follows the outdoor temperature with a ~6 h time constant

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const hourOfDay = (t) => { const d = new Date(t); return d.getHours() + d.getMinutes() / 60; };

// Repeatable noise in [-0.5, 0.5) per minute and channel
function noise(t, channel) {
  let x = (Math.floor(t / MIN) * 374761393 + channel * 668265263) | 0;
  x = Math.imul(x ^ (x >>> 13), 1274126177);
  return ((x ^ (x >>> 16)) >>> 0) / 4294967296 - 0.5;
}

/** Outdoor weather at time t, continuous in time (hourly rows sample it). */
export function outdoorAt(t) {
  const h = hourOfDay(t);
  const day = t / DAY;
  const diurnal = Math.sin((2 * Math.PI * (h - 9)) / 24);
  const temp = 9 + 3 * diurnal + 2 * Math.sin(day / 2.3);
  const rh = clamp(84 - 9 * diurnal + 5 * Math.sin(day / 1.7), 55, 99);
  const rain = Math.sin(day * 1.9) > 0.55;
  const cloudy = rain || Math.sin(day * 1.3 + 1) > -0.2;
  const isDay = h >= 7.5 && h < 18;
  const cloud = rain ? 100 : cloudy ? 80 : 20;
  return {
    temp_c: temp,
    rh,
    dew_point_c: dewPoint(temp, rh),
    press_hpa: 1005 + 9 * Math.sin(day / 1.5),
    precip_mm: rain ? 0.6 + 0.4 * Math.sin(day * 9) : 0,
    cloud_cover_pct: cloud,
    wind_speed_ms: 3 + 2 * Math.sin(day * 2.1),
    wind_dir_deg: (230 + 40 * Math.sin(day)) % 360,
    shortwave_wm2: isDay ? Math.max(0, 420 * Math.sin((Math.PI * (h - 7.5)) / 10.5)) * (1 - cloud / 130) : 0,
    weather_code: rain ? 61 : rh > 96 && !isDay ? 45 : cloudy ? 3 : isDay ? 1 : 0,
    is_day: isDay,
  };
}

function occupants(t) {
  const d = new Date(t);
  const weekend = d.getDay() === 0 || d.getDay() === 6;
  const h = hourOfDay(t);
  if (weekend) return h >= 1 && h < 9 ? 2 : 1.5;
  return h < 8 || h >= 17 ? 2 : 0;
}

function doorClosed(t) {
  const d = new Date(t);
  const m = d.getHours() * 60 + d.getMinutes();
  return m >= DOOR_CLOSED[0] * 60 + DOOR_CLOSED[1] && m < DOOR_CLOSED[0] * 60 + DOOR_CLOSED[1] + 30;
}

function airing(t) {
  const d = new Date(t);
  const m = d.getHours() * 60 + d.getMinutes();
  return AIRING.some(([h, mm]) => m >= h * 60 + mm && m < h * 60 + mm + 10);
}

/** Minute-by-minute indoor simulation; returns step(t) -> reading row. */
function createSimulator() {
  let co2 = 600;          // ppm
  let moisture = 1.5;     // g/m³ above outdoor absolute humidity
  let chill = 0;          // °C below the heating set point after airing
  let outdoorSlow = null; // outdoor temperature low-passed by the wall's thermal mass

  return function step(t) {
    const out = outdoorAt(t);
    const people = occupants(t);
    const open = airing(t);
    const k = (open ? ACH_AIRING : ACH_CLOSED) / 60;       // per minute

    co2 += k * (CO2_OUTDOOR - co2) + (people * CO2_PER_PERSON / 1000 / VOLUME) * 1e6;   // L -> m³ -> ppm
    moisture += -k * moisture + (people * WATER_PER_PERSON) / 60 / VOLUME;
    chill = open ? Math.min(2, chill + 0.15) : chill * 0.97;

    const h = hourOfDay(t);
    const temp = 20.6 + 0.5 * Math.sin((2 * Math.PI * (h - 13)) / 24) - chill;
    outdoorSlow = outdoorSlow == null ? out.temp_c : outdoorSlow + (out.temp_c - outdoorSlow) / WALL_LAG_MIN;
    const wall = outdoorSlow + WALL_FRSI * (temp - outdoorSlow);
    const ah = absoluteHumidity(out.temp_c, out.rh) + moisture;
    const rh = clamp(rhFromAbsolute(temp, ah), 5, 100);

    return {
      t,
      temp_c: temp + 0.06 * noise(t, 1),
      rh: rh + 0.4 * noise(t, 2),
      press_hpa: out.press_hpa + 0.4 + 0.05 * noise(t, 3),
      // The SCD-40 reads cooler and drier than the BME280, as the real pair does
      co2_ppm: Math.round(co2 + 20 * noise(t, 4)),
      scd_temp_c: temp - 1.2 + 0.1 * noise(t, 5),
      scd_rh: rh - 4 + 0.6 * noise(t, 6),
      wall_temp_c: wall + 0.03 * noise(t, 7),
      // The balcony probe reads warm in sunshine, as an unshielded real one would
      outdoor_temp_c: out.temp_c + 0.004 * out.shortwave_wm2 + 0.08 * noise(t, 8),
      window_open: open,
      door_open: !doorClosed(t),
    };
  };
}

function hourlyMeans(rows) {
  const byHour = new Map();
  for (const r of rows) {
    const h = Math.floor(r.t / HOUR) * HOUR;
    if (!byHour.has(h)) byHour.set(h, []);
    byHour.get(h).push(r);
  }
  return [...byHour].map(([t, rs]) => {
    const mean = (k) => rs.reduce((s, r) => s + Number(r[k]), 0) / rs.length;   // booleans -> fraction of the hour
    return { t, temp_c: mean('temp_c'), rh: mean('rh'), press_hpa: mean('press_hpa'), co2_ppm: mean('co2_ppm'),
      scd_temp_c: mean('scd_temp_c'), scd_rh: mean('scd_rh'), wall_temp_c: mean('wall_temp_c'),
      outdoor_temp_c: mean('outdoor_temp_c'), window_open: mean('window_open'), door_open: mean('door_open') };
  });
}

/**
 * Demo data source. history: how far back to simulate; cadenceMs: how often a new "live" reading arrives
 * (faster than the real node's 60 s so the demo visibly updates).
 */
export function createDemoSource({ now = Date.now(), historyDays = 8, cadenceMs = 15_000 } = {}) {
  const step = createSimulator();
  const rows = [];
  for (let t = Math.floor((now - historyDays * DAY) / MIN) * MIN; t <= now; t += MIN) rows.push(step(t));

  return {
    kind: 'demo',
    async needsLogin() { return false; },
    async readings(fromMs, { hourly = false } = {}) {
      const sel = rows.filter((r) => r.t >= fromMs);
      return hourly ? hourlyMeans(sel) : sel;
    },
    async weather(fromMs, toMs) {
      const out = [];
      for (let t = Math.ceil(fromMs / HOUR) * HOUR; t <= toMs; t += HOUR) out.push({ t, ...outdoorAt(t) });
      return out;
    },
    subscribe(onReading, onStatus) {
      onStatus?.('SUBSCRIBED');
      const id = setInterval(() => {
        const r = step(Date.now());
        rows.push(r);
        onReading(r);
      }, cadenceMs);
      return () => clearInterval(id);
    },
  };
}
