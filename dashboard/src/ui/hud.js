// Stat tiles: the current state at a glance. Each tile opens the matching panel.
import { dewPoint, surfaceRH } from '../physics.js';
import { fmt, weatherText } from './format.js';
import { wallRisk } from './panels.js';

function co2Status(ppm) {
  if (ppm == null) return null;
  if (ppm < 800) return { cls: 'is-good', icon: '✓', text: 'Fresh' };
  if (ppm < 1000) return { cls: 'is-warning', icon: '!', text: 'Getting stuffy' };
  return { cls: 'is-serious', icon: '!', text: 'Air out' };
}

function tile(id, label, value, sub, status) {
  return `<button type="button" class="tile" data-open="${id}">
    <span class="tile-label">${label}</span>
    <span class="tile-value">${value}</span>
    ${sub ? `<span class="tile-sub">${sub}</span>` : ''}
    ${status ? `<span class="status ${status.cls}"><span aria-hidden="true">${status.icon}</span> ${status.text}</span>` : ''}
  </button>`;
}

export function renderTiles(el, { latest, weatherNow, advice }) {
  const w = weatherNow ? weatherText(weatherNow.weather_code) : null;
  const open = advice?.action === 'open';
  const wall = latest?.wall_temp_c;
  const wallRh = wall != null && latest.rh != null ? surfaceRH(latest.temp_c, latest.rh, wall) : null;
  const windowsLabel = latest?.window_open === true ? 'Windows · one is open' : 'Windows';
  el.innerHTML = [
    tile('climate', 'Inside', fmt(latest?.temp_c, 1, '°C'), `${fmt(latest?.rh, 0, '%')} humidity`),
    wall != null
      ? tile('wall', 'Wall', fmt(wall, 1, '°C'), `${fmt(wallRh, 0, '%')} humidity at the surface`, wallRisk(wallRh))
      : tile('wall', 'Dew point', fmt(latest && dewPoint(latest.temp_c, latest.rh), 1, '°C'), 'walls must stay warmer'),
    tile('co2', 'CO₂', fmt(latest?.co2_ppm, 0, 'ppm'), null, co2Status(latest?.co2_ppm)),
    tile('outdoor', 'Outside', w ? `${w.icon} ${fmt(weatherNow.temp_c, 1, '°C')}` : '–',
      w ? `${w.text} · ${fmt(weatherNow.rh, 0, '%')}` : 'no weather data'),
    advice && advice.action !== 'unknown'
      ? tile('outdoor', windowsLabel, open ? 'Open now' : 'Keep closed', advice.reasons[0],
        open ? { cls: 'is-warning', icon: '↻', text: 'Air for 5–10 min' } : { cls: 'is-good', icon: '✓', text: 'All fine' })
      : '',
  ].join('');
}
