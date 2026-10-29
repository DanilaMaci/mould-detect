// Sun position for the scene's daylight: NOAA's general solar position equations (fractional-year Fourier series
// for the equation of time and declination; accurate to well under a degree, plenty for shadows). Pure functions,
// tested in tests/sun.test.js.

const RAD = Math.PI / 180;

/**
 * Sun elevation above the horizon and azimuth clockwise from north, both in degrees, at time `ms` (Unix ms) for a
 * place at latDeg (north positive) and lonDeg (east positive).
 */
export function sunPosition(ms, latDeg, lonDeg) {
  const d = new Date(ms);
  const start = Date.UTC(d.getUTCFullYear(), 0, 1);
  const leap = new Date(Date.UTC(d.getUTCFullYear(), 1, 29)).getUTCMonth() === 1;
  const hours = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  const dayOfYear = Math.floor((ms - start) / 86_400_000) + 1;
  const g = ((2 * Math.PI) / (leap ? 366 : 365)) * (dayOfYear - 1 + (hours - 12) / 24);   // fractional year, rad

  const eqTimeMin = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g)
    - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
    + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);   // rad

  const trueSolarMin = hours * 60 + eqTimeMin + 4 * lonDeg;
  const ha = (trueSolarMin / 4 - 180) * RAD;   // hour angle, 0 at solar noon
  const lat = latDeg * RAD;

  const sinEl = Math.sin(lat) * Math.sin(decl) + Math.cos(lat) * Math.cos(decl) * Math.cos(ha);
  const elevation = Math.asin(Math.max(-1, Math.min(1, sinEl))) / RAD;
  const azimuth = (Math.atan2(Math.sin(ha), Math.cos(ha) * Math.sin(lat) - Math.tan(decl) * Math.cos(lat)) / RAD + 540) % 360;
  return { elevation, azimuth };
}

/**
 * Direction towards the sun in scene coordinates (unit vector [x, y, z]) for a room whose balcony wall (scene -z)
 * faces compass bearing `facingDeg`. Scene +x is to the right when looking out of the balcony.
 */
export function sunDirection({ elevation, azimuth }, facingDeg) {
  const rel = (azimuth - facingDeg) * RAD;
  const el = elevation * RAD;
  return [Math.cos(el) * Math.sin(rel), Math.sin(el), -Math.cos(el) * Math.cos(rel)];
}
