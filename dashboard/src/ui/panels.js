// Side-panel content for each hotspot. Each builder writes into `el` and returns the charts it created
// (so the caller can destroy them). ctx: { readings, weather, latest, weatherNow, hourly, advice }.
import { absoluteHumidity, dewPoint, surfaceRH, surfaceTempForRH } from '../physics.js';
import { lineChart } from './charts.js';
import { escapeHtml, fmt, weatherText } from './format.js';
import { hoursWhere, periods } from './periods.js';

const MIN = 60_000;
const HOUR = 3_600_000;
const MOULD_RH = 80;   // % surface humidity sustained over time: common mould-growth threshold

const series = (rows, value) => rows.map((r) => [r.t, value(r) ?? null]);

// Window open / door closed (from the room node's buttons) as shaded chart bands. Hourly rows hold the fraction of
// the hour in each state: any opening in the hour marks it, as does any door closure.
export function stateBands(readings, hourly) {
  const opts = { stepMs: hourly ? HOUR : MIN, maxGapMs: hourly ? 2 * HOUR + 1 : 5 * MIN };
  const windows = periods(readings, (r) => r.window_open != null && r.window_open > 0, opts);
  const doors = periods(readings, (r) => r.door_open != null && r.door_open < 1, opts);
  return [
    ...(windows.length ? [{ periods: windows, color: '--series-1', alpha: 0.13 }] : []),
    ...(doors.length ? [{ periods: doors, color: '--warning', alpha: 0.2 }] : []),
  ];
}

const BANDS_NOTE = 'Blue bands: a window was open; amber bands: the room door was closed (buttons on the room node). ' +
  'Dashed lines bridge times without data.';
const safe = (f) => (r) => { const v = f(r); return Number.isFinite(v) ? v : null; };

function nowGrid(items) {
  return `<div class="now-grid">${items.map(([label, value, sub]) =>
    `<div class="now"><span class="now-label">${label}</span><span class="now-value">${value}</span>${
      sub ? `<span class="now-sub">${sub}</span>` : ''}</div>`).join('')}</div>`;
}

function section(el, title, note) {
  const s = document.createElement('section');
  s.className = 'panel-section';
  s.innerHTML = `<h3>${title}</h3>${note ? `<p class="note">${note}</p>` : ''}`;
  el.appendChild(s);
  return s;
}

function adviceBlock(advice) {
  if (!advice || advice.action === 'unknown') return '';
  const open = advice.action === 'open';
  return `<div class="advice ${open ? 'is-warning' : 'is-good'}" role="status">
    <span class="advice-icon" aria-hidden="true">${open ? '↻' : '✓'}</span>
    <div><strong>${open ? 'Open the windows wide for 5–10 minutes' : 'No need to air right now'}</strong>
    <ul>${advice.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul></div></div>`;
}

/** Status of the humidity at the wall surface (instantaneous; mould needs it sustained). */
export function wallRisk(rh) {
  if (rh == null || !Number.isFinite(rh)) return null;
  if (rh < 70) return { cls: 'is-good', icon: '✓', text: 'Dry enough' };
  if (rh < MOULD_RH) return { cls: 'is-warning', icon: '!', text: 'Watch' };
  return { cls: 'is-serious', icon: '!', text: 'Mould risk if it lasts' };
}

export const PANELS = {
  climate(el, { readings, weather, latest, hourly }) {
    const gap = hourly ? 2 * HOUR + 1 : 5 * MIN;
    el.insertAdjacentHTML('beforeend', nowGrid([
      ['Temperature', fmt(latest?.temp_c, 1, '°C')],
      ['Humidity', fmt(latest?.rh, 0, '%')],
      ['Dew point', fmt(latest && dewPoint(latest.temp_c, latest.rh), 1, '°C')],
      ['Pressure', fmt(latest?.press_hpa, 0, 'hPa')],
    ]));
    const charts = [];
    charts.push(lineChart(section(el, 'Temperature', BANDS_NOTE), [
      { label: 'Room · BME280', color: '--series-1', points: series(readings, (r) => r.temp_c), gapMs: gap },
      { label: 'Room · SCD-40', color: '--series-2', points: series(readings, (r) => r.scd_temp_c), gapMs: gap },
      { label: 'Outside', color: '--series-3', points: series(weather, (r) => r.temp_c) },
    ], { unit: '°C', bands: stateBands(readings, hourly) }));
    charts.push(lineChart(section(el, 'Relative humidity',
      'The two room sensors disagree by a few percent; a salt-jar test will show which one to trust.'), [
      { label: 'Room · BME280', color: '--series-1', points: series(readings, (r) => r.rh), gapMs: gap },
      { label: 'Room · SCD-40', color: '--series-2', points: series(readings, (r) => r.scd_rh), gapMs: gap },
      { label: 'Outside', color: '--series-3', points: series(weather, (r) => r.rh) },
    ], { unit: '%', decimals: 0 }));
    charts.push(lineChart(section(el, 'Air pressure',
      'Agreement between the two lines confirms the sensor and the weather location.'), [
      { label: 'Room · BME280', color: '--series-1', points: series(readings, (r) => r.press_hpa), gapMs: gap },
      { label: 'Open-Meteo', color: '--series-3', points: series(weather, (r) => r.press_hpa) },
    ], { unit: 'hPa', decimals: 1 }));
    return charts;
  },

  co2(el, { readings, latest, hourly }) {
    const gap = hourly ? 2 * HOUR + 1 : 5 * MIN;
    el.insertAdjacentHTML('beforeend', nowGrid([
      ['CO₂', fmt(latest?.co2_ppm, 0, 'ppm')],
      ['Temperature', fmt(latest?.scd_temp_c, 1, '°C'), 'SCD-40'],
      ['Humidity', fmt(latest?.scd_rh, 0, '%'), 'SCD-40'],
    ]));
    return [lineChart(section(el, 'CO₂',
      'Outdoor air is about 420 ppm. Each person adds CO₂; above 1000 ppm the air feels stuffy and it is time to air out. ' +
      `Sharp drops are window openings. ${BANDS_NOTE}`), [
      { label: 'CO₂', color: '--series-1', points: series(readings, (r) => r.co2_ppm), gapMs: gap },
    ], { unit: 'ppm', decimals: 0, height: 200, threshold: { value: 1000, label: 'air out above 1000 ppm' },
      bands: stateBands(readings, hourly) })];
  },

  outdoor(el, { readings, weather, latest, weatherNow, advice, hourly }) {
    const gap = hourly ? 2 * HOUR + 1 : 5 * MIN;
    const w = weatherNow;
    const desc = w ? weatherText(w.weather_code) : null;
    el.insertAdjacentHTML('beforeend', nowGrid([
      ['Now', desc ? `${desc.icon} ${fmt(w.temp_c, 1, '°C')}` : '–', desc?.text],
      ['Balcony probe', fmt(latest?.outdoor_temp_c, 1, '°C'), 'measured on the balcony'],
      ['Humidity', fmt(w?.rh, 0, '%')],
      ['Wind', fmt(w?.wind_speed_ms, 1, 'm/s')],
      ['Rain', fmt(w?.precip_mm, 1, 'mm/h')],
    ]));
    el.insertAdjacentHTML('beforeend', adviceBlock(advice));
    const ah = safe((r) => absoluteHumidity(r.temp_c, r.rh));
    const charts = [];
    charts.push(lineChart(section(el, 'Water in the air',
      'Airing dries the room only when the outside line is below the inside line: cold outdoor air holds little water, ' +
      'even at high relative humidity.'), [
      { label: 'Inside', color: '--series-1', points: series(readings, ah), gapMs: gap },
      { label: 'Outside', color: '--series-3', points: series(weather, ah) },
    ], { unit: 'g/m³', decimals: 1 }));
    charts.push(lineChart(section(el, 'Outside temperature',
      'Open-Meteo for the area, including the forecast for the next two days, and the probe on the balcony. ' +
      'In direct sun the probe reads too warm unless its shield works.'), [
      { label: 'Open-Meteo', color: '--series-3', points: series(weather, (r) => r.temp_c) },
      { label: 'Balcony probe', color: '--series-1', points: series(readings, (r) => r.outdoor_temp_c), gapMs: gap },
    ], { unit: '°C', showNow: true }));
    return charts;
  },

  wall(el, { readings, weather, latest, hourly }) {
    const gap = hourly ? 2 * HOUR + 1 : 5 * MIN;
    const crit = safe((r) => surfaceTempForRH(r.temp_c, r.rh, MOULD_RH));
    const dew = safe((r) => dewPoint(r.temp_c, r.rh));
    const atWall = safe((r) => (r.wall_temp_c == null ? null : surfaceRH(r.temp_c, r.rh, r.wall_temp_c)));
    const wallNow = latest?.wall_temp_c;
    const rhNow = latest && atWall(latest);
    el.insertAdjacentHTML('beforeend', `<p class="lead">Mould grows where air touches a <em>cold</em> surface and stays
      above about ${MOULD_RH} % humidity there for long periods. The room air can look fine while the coldest wall
      spot is far wetter. ${wallNow == null
    ? 'The wall probe is not reporting right now; the lines below show how cold the wall may get.'
    : 'A probe on the balcony wall measures its surface temperature; with the room air it gives the humidity right at the wall.'}</p>`);
    el.insertAdjacentHTML('beforeend', nowGrid([
      ['Wall surface', fmt(wallNow, 1, '°C'), 'probe on the balcony wall'],
      ['Humidity at the wall', fmt(rhNow, 0, '%'), wallRisk(rhNow)?.text],
      ['Mould-critical wall', fmt(latest && crit(latest), 1, '°C'), `wall below this → over ${MOULD_RH} % at the surface`],
      ['Dew point', fmt(latest && dew(latest), 1, '°C'), 'wall below this → condensation'],
      ['Hours above ' + MOULD_RH + ' %', fmt(hoursWhere(readings, (r) => (atWall(r) ?? 0) >= MOULD_RH,
        { stepMs: hourly ? HOUR : MIN, maxGapMs: gap }), 1, 'h'), 'at the wall, in this range (darkens the 3D stain)'],
    ]));
    const bands = stateBands(readings, hourly);
    return [
      lineChart(section(el, 'How cold may the wall get?',
        'The measured wall (blue) must stay above the orange line; below the grey dashed line water condenses.'), [
        { label: 'Wall · probe', color: '--series-1', points: series(readings, (r) => r.wall_temp_c), gapMs: gap },
        { label: `Critical (${MOULD_RH} % at wall)`, color: '--series-2', points: series(readings, crit), gapMs: gap },
        { label: 'Dew point', color: '--text-muted', dash: [4, 4], points: series(readings, dew), gapMs: gap },
        { label: 'Outside', color: '--series-3', points: series(weather, (r) => r.temp_c) },
      ], { unit: '°C', bands }),
      lineChart(section(el, 'Humidity at the wall surface',
        `Room air cooled to the wall's temperature. Sustained hours above ${MOULD_RH} % are what mould needs; ` +
        'short peaks after showers or cooking are normal. Uses the BME280 until the salt test settles which room ' +
        `sensor is right. ${BANDS_NOTE}`), [
        { label: 'At the wall', color: '--series-2', points: series(readings, atWall), gapMs: gap },
        { label: 'Room air', color: '--series-1', points: series(readings, (r) => r.rh), gapMs: gap },
      ], { unit: '%', decimals: 0, threshold: { value: MOULD_RH, label: `mould risk above ${MOULD_RH} %` }, bands }),
    ];
  },
};
