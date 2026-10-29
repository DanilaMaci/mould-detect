// Sun position against astronomical facts that do not come from the formula under test: the noon elevation is
// 90° − latitude + declination (solstice declination 23.44°, equinox ~0°), noon is due south in the north and due
// north in the south, and the equation of time peaks at about +16.4 min in early November (solar noon ~11:44 UTC
// on the Greenwich meridian). Run: npm test (in dashboard/)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sunDirection, sunPosition } from '../src/sun.js';

const near = (actual, expected, tol, msg) =>
  assert.ok(Math.abs(actual - expected) <= tol, `${msg}: ${actual.toFixed(3)} vs ${expected} ± ${tol}`);

// Highest point of the day, searched minute by minute (independent of the formula's own noon)
function dayMax(y, m, d, lat, lon) {
  let best = { elevation: -90 };
  for (let min = 0; min < 1440; min++) {
    const t = Date.UTC(y, m, d, 0, min);
    const p = sunPosition(t, lat, lon);
    if (p.elevation > best.elevation) best = { ...p, t };
  }
  return best;
}

test('June solstice noon at 51.5° N: elevation 90 − 51.5 + 23.44, due south', () => {
  const p = dayMax(2026, 5, 21, 51.5, 0);
  near(p.elevation, 61.94, 0.3, 'elevation');
  near(p.azimuth, 180, 1, 'azimuth');
});

test('March equinox noon at 40° N: elevation about 50°', () => {
  near(dayMax(2026, 2, 20, 40, 0).elevation, 50, 0.6, 'elevation');
});

test('June solstice noon at 33.9° S: elevation 90 − 33.9 − 23.44, due north', () => {
  const p = dayMax(2026, 5, 21, -33.9, 18.4);
  near(p.elevation, 32.66, 0.3, 'elevation');
  assert.ok(p.azimuth < 2 || p.azimuth > 358, `azimuth ${p.azimuth}`);
});

test('early November solar noon on the Greenwich meridian is ~16 min early', () => {
  const noon = new Date(dayMax(2026, 10, 3, 51.5, 0).t);
  const min = noon.getUTCHours() * 60 + noon.getUTCMinutes();
  near(min, 11 * 60 + 43.6, 2, 'minutes after midnight UTC');
});

test('morning sun is in the east, afternoon in the west, midnight below the horizon', () => {
  near(sunPosition(Date.UTC(2026, 5, 21, 6), 51.5, 0).azimuth, 80, 15, 'morning azimuth');
  near(sunPosition(Date.UTC(2026, 5, 21, 18), 51.5, 0).azimuth, 280, 15, 'evening azimuth');
  assert.ok(sunPosition(Date.UTC(2026, 11, 21, 0), 51.5, 0).elevation < -40);
});

test('scene direction: sun straight ahead of a south-facing balcony is towards -z', () => {
  const [x, y, z] = sunDirection({ elevation: 0, azimuth: 180 }, 180);
  near(x, 0, 1e-9, 'x'); near(y, 0, 1e-9, 'y'); near(z, -1, 1e-9, 'z');
  const right = sunDirection({ elevation: 0, azimuth: 270 }, 180);   // west, i.e. right when looking south
  near(right[0], 1, 1e-9, 'west is +x for a south-facing balcony');
  near(sunDirection({ elevation: 90, azimuth: 0 }, 180)[1], 1, 1e-9, 'zenith is +y');
});

test('solar noon moves 1 h earlier per 15° east', () => {
  const noonMin = (lon) => { const t = new Date(dayMax(2026, 10, 3, 30, lon).t); return t.getUTCHours() * 60 + t.getUTCMinutes(); };
  near(noonMin(0) - noonMin(90), 360, 2, 'minutes between 0° and 90° E');
});
