// Number, time and weather formatting shared by the HUD, tags and panels.

export const fmt = (v, decimals = 1, unit = '') =>
  v == null || Number.isNaN(v) ? '–' : `${v.toFixed(decimals)}${unit ? ` ${unit}` : ''}`;

export function ago(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

export const clock = (t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// WMO weather codes as used by Open-Meteo
const WMO = [
  [[0], 'Clear sky', '☀︎'], [[1], 'Mainly clear', '🌤'], [[2], 'Partly cloudy', '⛅︎'], [[3], 'Overcast', '☁︎'],
  [[45, 48], 'Fog', '🌫'], [[51, 53, 55], 'Drizzle', '🌦'], [[56, 57], 'Freezing drizzle', '🌧'],
  [[61, 63, 65], 'Rain', '🌧'], [[66, 67], 'Freezing rain', '🌧'], [[71, 73, 75, 77], 'Snow', '🌨'],
  [[80, 81, 82], 'Rain showers', '🌦'], [[85, 86], 'Snow showers', '🌨'], [[95, 96, 99], 'Thunderstorm', '⛈'],
];

export function weatherText(code) {
  const hit = WMO.find(([codes]) => codes.includes(code));
  return hit ? { text: hit[1], icon: hit[2] } : { text: 'Unknown', icon: '·' };
}

export const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
