// The demo data must look like real data: plausible ranges, same columns as Supabase, airing visible in CO2.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDemoSource } from '../src/data/demo.js';

const NOW = new Date(2026, 9, 21, 22, 0).getTime();   // local time, a Wednesday evening
const HOUR = 3_600_000;

test('readings have the Supabase columns and plausible values', async () => {
  const src = createDemoSource({ now: NOW, historyDays: 3 });
  const rows = await src.readings(NOW - 48 * HOUR);
  assert.ok(rows.length > 2800, `rows: ${rows.length}`);
  for (const k of ['t', 'temp_c', 'rh', 'press_hpa', 'co2_ppm', 'scd_temp_c', 'scd_rh', 'wall_temp_c',
    'outdoor_temp_c', 'window_open', 'door_open']) assert.ok(k in rows[0], k);
  for (const r of rows) {
    assert.ok(r.temp_c > 15 && r.temp_c < 25, `temp ${r.temp_c}`);
    // The cold wall spot sits between outdoor and room temperature
    assert.ok(r.wall_temp_c < r.temp_c && r.wall_temp_c > r.outdoor_temp_c - 3, `wall ${r.wall_temp_c}`);
    assert.equal(typeof r.window_open, 'boolean');
    assert.equal(typeof r.door_open, 'boolean');
    assert.ok(r.rh > 25 && r.rh < 90, `rh ${r.rh}`);
    assert.ok(r.co2_ppm > 380 && r.co2_ppm < 2500, `co2 ${r.co2_ppm}`);
  }
});

test('morning airing at 08:00 drops CO2', async () => {
  const src = createDemoSource({ now: NOW, historyDays: 2 });
  const rows = await src.readings(NOW - 30 * HOUR);
  const at = (h, m) => rows.find((r) => { const d = new Date(r.t); return d.getHours() === h && d.getMinutes() === m; });
  assert.ok(at(8, 9).co2_ppm < at(7, 59).co2_ppm - 300, `${at(7, 59).co2_ppm} -> ${at(8, 9).co2_ppm}`);
  assert.ok(at(8, 5).window_open && !at(7, 59).window_open, 'window state follows the airing');
});

test('hourly mode and weather rows', async () => {
  const src = createDemoSource({ now: NOW, historyDays: 8 });
  const hourly = await src.readings(NOW - 7 * 24 * HOUR, { hourly: true });
  assert.ok(hourly.length >= 168 && hourly.length <= 170, `hourly rows: ${hourly.length}`);
  const weather = await src.weather(NOW - 24 * HOUR, NOW + 48 * HOUR);
  assert.equal(weather.length, 73);
  for (const w of weather) assert.ok(Number.isInteger(w.weather_code) && typeof w.is_day === 'boolean');
});
