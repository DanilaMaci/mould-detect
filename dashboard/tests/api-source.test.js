// The own-API data source must give main.js the same shapes as the Supabase source.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createApiSource } from '../src/data/api.js';

const T0 = Date.parse('2026-10-26T12:00:00Z');

function fakeApi(rows) {
  const calls = [];
  const fetchFn = async (url, opts) => {
    calls.push({ url: new URL(url), auth: opts.headers.Authorization });
    const u = new URL(url);
    if (u.pathname === '/api/weather') {
      return { ok: true, json: async () => [{ observed_at: '2026-10-26T11:00:00.000000Z', temp_c: 9.5, is_day: true }] };
    }
    const since = Date.parse(u.searchParams.get('since'));
    const body = u.searchParams.get('hourly')
      ? [{ hour: '2026-10-26T11:00:00.000000Z', device_id: 'node1', temp_c: 21, window_open: 0.5, samples: 60 }]
      : rows.filter((r) => Date.parse(r.measured_at) >= since);
    return { ok: true, json: async () => body };
  };
  return { calls, fetchFn };
}

const row = (min, temp) => ({ measured_at: new Date(T0 + min * 60_000).toISOString(), device_id: 'node1', temp_c: temp,
  rh: 50, door_open: true });

test('readings and weather in the Supabase source shape, with the read token', async () => {
  const api = fakeApi([row(0, 21), row(1, 22)]);
  const src = createApiSource({ baseUrl: 'http://127.0.0.1:8200/', readToken: 'tok', deviceId: 'node1', fetchFn: api.fetchFn });
  const rs = await src.readings(T0 - 1000);
  assert.deepEqual(rs[1], { t: T0 + 60_000, temp_c: 22, rh: 50, door_open: true });
  const hourly = await src.readings(T0 - 3_600_000, { hourly: true });
  assert.deepEqual(hourly, [{ t: Date.parse('2026-10-26T11:00:00Z'), temp_c: 21, window_open: 0.5 }]);
  const w = await src.weather(T0 - 3_600_000, T0);
  assert.deepEqual(w, [{ t: Date.parse('2026-10-26T11:00:00Z'), temp_c: 9.5, is_day: true }]);
  assert.equal(api.calls[0].auth, 'Bearer tok');
  assert.equal(api.calls[0].url.searchParams.get('device_id'), 'node1');
  assert.equal(api.calls[1].url.searchParams.get('hourly'), '1');
  assert.equal(await src.needsLogin(), false);
});

test('API errors surface with status and message', async () => {
  const fetchFn = async () => ({ ok: false, status: 401, statusText: 'Unauthorized',
    json: async () => ({ error: 'missing or wrong read token' }) });
  const src = createApiSource({ baseUrl: 'http://x', readToken: 'bad', deviceId: 'node1', fetchFn });
  await assert.rejects(src.readings(T0), /API 401: missing or wrong read token/);
});

test('subscribe delivers each new row once and reports status', async () => {
  const realNow = Date.now;
  Date.now = () => T0 + 30_000;   // the row at T0 is older than the subscription: not delivered
  try {
    const rows = [row(0, 21)];
    const api = fakeApi(rows);
    const src = createApiSource({ baseUrl: 'http://x', readToken: 'tok', deviceId: 'node1', pollMs: 10, fetchFn: api.fetchFn });
    const got = [];
    const statuses = [];
    const stop = src.subscribe((r) => got.push(r.temp_c), (s) => statuses.push(s));
    await new Promise((r) => setTimeout(r, 25));
    rows.push(row(1, 23));   // a new reading arrives at the API
    await new Promise((r) => setTimeout(r, 45));   // several more polls
    stop();
    assert.deepEqual(got, [23]);
    assert.deepEqual(statuses, ['SUBSCRIBED']);
  } finally {
    Date.now = realNow;
  }
});
