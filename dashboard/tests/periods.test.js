// Window/door periods and data gaps for the charts. Run: npm test (in dashboard/)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hoursWhere, periods, splitGaps } from '../src/ui/periods.js';

const MIN = 60_000;
const rows = (states) => states.map((s, i) => ({ t: i * MIN, open: s }));

test('periods: start at the first row in the state, end at the first row out of it', () => {
  assert.deepEqual(periods(rows([0, 1, 1, 0, 0, 1, 0]), (r) => r.open, { stepMs: MIN }),
    [[1 * MIN, 3 * MIN], [5 * MIN, 6 * MIN]]);
});

test('periods: a state that lasts to the end counts its last row for one step', () => {
  assert.deepEqual(periods(rows([0, 1, 1]), (r) => r.open, { stepMs: MIN }), [[1 * MIN, 3 * MIN]]);
  assert.deepEqual(periods(rows([0, 0]), (r) => r.open, { stepMs: MIN }), []);
  assert.deepEqual(periods([], (r) => r.open, { stepMs: MIN }), []);
});

test('periods: an outage ends the period instead of stretching it', () => {
  const r = [{ t: 0, open: 1 }, { t: MIN, open: 1 }, { t: 90 * MIN, open: 1 }, { t: 91 * MIN, open: 0 }];
  assert.deepEqual(periods(r, (x) => x.open, { stepMs: MIN, maxGapMs: 5 * MIN }),
    [[0, 2 * MIN], [90 * MIN, 91 * MIN]]);
});

test('splitGaps: nulls dropped, long jumps become gaps with both end values', () => {
  const pts = [[0, 1], [MIN, null], [2 * MIN, 3], [60 * MIN, 5], [61 * MIN, 6]];
  const { measured, gaps } = splitGaps(pts, 5 * MIN);
  assert.deepEqual(measured, [[0, 1], [2 * MIN, 3], [60 * MIN, 5], [61 * MIN, 6]]);
  assert.deepEqual(gaps, [[2 * MIN, 3, 60 * MIN, 5]]);
  assert.deepEqual(splitGaps(pts).gaps, [], 'no gapMs: no gaps');
});

test('splitGaps: an isolated point after a restart is joined on both sides', () => {
  const pts = [[0, 800], [30 * MIN, 650], [70 * MIN, 900], [71 * MIN, 905]];
  assert.equal(splitGaps(pts, 5 * MIN).gaps.length, 2);
});

test('hoursWhere: minutes add up, outages count one step only', () => {
  const r = Array.from({ length: 121 }, (_, i) => ({ t: i * MIN, wet: i < 60 }));   // 60 wet minutes, 61 dry
  assert.equal(hoursWhere(r, (x) => x.wet, { stepMs: MIN, maxGapMs: 5 * MIN }), 1);
  const outage = [{ t: 0, wet: true }, { t: 10 * 60 * MIN, wet: true }];   // node off for 10 h while wet
  assert.equal(hoursWhere(outage, (x) => x.wet, { stepMs: MIN, maxGapMs: 5 * MIN }), 2 / 60);
  assert.equal(hoursWhere([], (x) => x.wet, { stepMs: MIN }), 0);
});
