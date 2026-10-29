// Physics checked against independent reference values and limiting cases. Run: npm test (in dashboard/)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  absoluteHumidity, dewPoint, glassFog, glassSurfaceTemp, rhFromAbsolute, satVapourPressure, surfaceRH, surfaceTempForRH,
  ventilationAdvice,
} from '../src/physics.js';

const near = (actual, expected, tol, msg) =>
  assert.ok(Math.abs(actual - expected) <= tol, `${msg}: ${actual} vs ${expected} ± ${tol}`);

test('saturation vapour pressure within 0.4 % of steam tables (the Magnus formula\'s accuracy)', () => {
  for (const [t, ref] of [[0, 6.112], [20, 23.39], [30, 42.47], [-10, 2.865]]) {   // kPa x 10
    near(satVapourPressure(t), ref, ref * 0.004, `${t} °C`);
  }
});

test('absolute humidity of saturated air at 20 °C is about 17.3 g/m³', () => {
  near(absoluteHumidity(20, 100), 17.3, 0.1, 'AH');
});

test('limiting cases', () => {
  near(dewPoint(18.5, 100), 18.5, 1e-9, 'dew point at 100 % RH equals air temperature');
  near(surfaceRH(21, 55, 21), 55, 1e-9, 'surface at air temperature has room RH');
  near(surfaceTempForRH(21, 55, 100), dewPoint(21, 55), 1e-9, '100 % at the surface is the dew point');
  near(rhFromAbsolute(12, absoluteHumidity(12, 73)), 73, 1e-9, 'RH -> AH -> RH round trip');
  assert.equal(surfaceRH(20, 60, 5), 100, 'capped at 100 % below the dew point');
});

test('worked example: 20 °C / 60 % room, 15 °C wall', () => {
  near(dewPoint(20, 60), 12.0, 0.05, 'dew point');
  near(surfaceRH(20, 60, 15), 82.2, 0.2, 'surface RH');
  assert.ok(surfaceTempForRH(20, 60, 80) > 15 && surfaceTempForRH(20, 60, 80) < 16, 'critical wall temp between 15 and 16 °C');
});

test('ventilation advice', () => {
  assert.equal(ventilationAdvice({ indoor: { t: 21, rh: 50, co2: 1200 }, outdoor: { t: 8, rh: 85 } }).action, 'open', 'stale air');
  const dry = ventilationAdvice({ indoor: { t: 20, rh: 65, co2: 600 }, outdoor: { t: 5, rh: 90 } });
  assert.equal(dry.action, 'open', 'humid room, dry outside air');
  assert.ok(dry.dryingGain > 3, `drying gain ${dry.dryingGain}`);
  assert.equal(ventilationAdvice({ indoor: { t: 21, rh: 45, co2: 600 }, outdoor: { t: 8, rh: 85 } }).action, 'keep', 'all fine');
  assert.equal(ventilationAdvice({ indoor: { t: 20, rh: 65, co2: 600 }, outdoor: { t: 24, rh: 80 } }).action, 'keep',
    'humid room but wetter outside air');
  assert.equal(ventilationAdvice({ indoor: null, outdoor: null }).action, 'unknown');
});

test('glass surface temperature: limiting cases and a hand-worked value', () => {
  near(glassSurfaceTemp(20, 20), 20, 1e-9, 'no temperature difference: glass at room temperature');
  near(glassSurfaceTemp(20, 0, { u: 0 }), 20, 1e-9, 'perfect insulator: glass at room temperature');
  // 20 °C inside, 0 °C outside, U 2.8, Rsi 0.13: 20 − 0.364 × 20 = 12.72 °C
  near(glassSurfaceTemp(20, 0), 12.72, 1e-9, 'double glazing');
});

test('glass fog: clear in mild weather, full when the glass is below the dew point', () => {
  assert.equal(glassFog(20, 50, 10), 0, 'dry room, mild outside');
  assert.equal(glassFog(20, 70, -5), 1, 'humid room, frost outside: glass 10.9 °C < dew point 14.4 °C');
  assert.equal(glassFog(20, null, 0), 0, 'missing data: no fog');
});
