// Turn per-row states into time periods and find the gaps in a series: pure functions, tested in
// tests/periods.test.js.

/**
 * Periods where test(row) holds, as [[startMs, endMs], ...]. A period ends at the next row where it no longer
 * holds; the last row of a period counts for stepMs (its sampling interval). A jump longer than maxGapMs between
 * rows also ends a period, so a node that was switched off does not stretch a window opening over the outage.
 */
export function periods(rows, test, { stepMs, maxGapMs = Infinity }) {
  const out = [];
  let start = null;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const prev = rows[i - 1];
    if (start != null && prev && r.t - prev.t > maxGapMs) {
      out.push([start, prev.t + stepMs]);
      start = null;
    }
    if (test(r)) {
      if (start == null) start = r.t;
    } else if (start != null) {
      out.push([start, r.t]);
      start = null;
    }
  }
  if (start != null) out.push([start, rows.at(-1).t + stepMs]);
  return out;
}

/**
 * Split [[t, value|null], ...] into the measured points and the gaps between them: null values are dropped, and
 * every jump longer than gapMs between consecutive measured points becomes a gap [t0, v0, t1, v1]. With no gapMs
 * there are no gaps.
 */
export function splitGaps(points, gapMs) {
  const measured = points.filter((p) => p[1] != null && Number.isFinite(p[1]));
  const gaps = [];
  if (gapMs) {
    for (let i = 1; i < measured.length; i++) {
      const [t0, v0] = measured[i - 1];
      const [t1, v1] = measured[i];
      if (t1 - t0 > gapMs) gaps.push([t0, v0, t1, v1]);
    }
  }
  return { measured, gaps };
}

/**
 * Hours during which test(row) held. Each row counts until the next row; across a gap longer than maxGapMs (node
 * off) and for the last row it counts stepMs only, so outages are not counted as hours in either state.
 */
export function hoursWhere(rows, test, { stepMs, maxGapMs = Infinity }) {
  let ms = 0;
  for (let i = 0; i < rows.length; i++) {
    if (!test(rows[i])) continue;
    const next = rows[i + 1];
    const dt = next ? next.t - rows[i].t : stepMs;
    ms += dt > maxGapMs ? stepMs : dt;
  }
  return ms / 3_600_000;
}
