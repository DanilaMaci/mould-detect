// Time-series charts on uPlot. One unit per chart (never two y-axes); legend doubles as the hover readout;
// every chart has a table view for accessibility. Data gaps (node off) are bridged with a dashed line so the shape
// stays readable without pretending there were measurements; shaded bands mark periods (window open, door closed).
import uPlot from 'https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/uPlot.esm.js';
import { clock, escapeHtml, fmt } from './format.js';
import { splitGaps } from './periods.js';

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Insert a null after any jump longer than gapMs so missing data shows as a gap, not a straight line. */
function withGaps(points, gapMs) {
  if (!gapMs) return points;
  const out = [];
  for (let i = 0; i < points.length; i++) {
    if (i > 0 && points[i][0] - points[i - 1][0] > gapMs) out.push([points[i - 1][0] + 1, null]);
    out.push(points[i]);
  }
  return out;
}

function thresholdPlugin({ value, label }) {
  return {
    hooks: {
      draw: (u) => {
        const dpr = window.devicePixelRatio || 1;
        const y = u.valToPos(value, 'y', true);
        const { ctx } = u;
        ctx.save();
        ctx.strokeStyle = token('--text-muted');
        ctx.lineWidth = dpr;
        ctx.setLineDash([4 * dpr, 4 * dpr]);
        ctx.beginPath();
        ctx.moveTo(u.bbox.left, y);
        ctx.lineTo(u.bbox.left + u.bbox.width, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = token('--text-secondary');
        ctx.font = `${11 * dpr}px system-ui, -apple-system, sans-serif`;
        ctx.fillText(label, u.bbox.left + 6 * dpr, y - 5 * dpr);
        ctx.restore();
      },
    },
  };
}

// Dashed, fainter straight line across each gap, in the series' colour: "no data here, joined for readability"
function gapBridgePlugin(seriesGaps, colors) {
  return {
    hooks: {
      draw: (u) => {
        const dpr = window.devicePixelRatio || 1;
        const { ctx } = u;
        ctx.save();
        ctx.beginPath();
        ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
        ctx.clip();
        ctx.lineWidth = 1.5 * dpr;
        ctx.setLineDash([5 * dpr, 4 * dpr]);
        ctx.globalAlpha = 0.55;
        seriesGaps.forEach((gaps, i) => {
          if (!gaps.length || u.series[i + 1].show === false) return;
          ctx.strokeStyle = colors[i];
          ctx.beginPath();
          for (const [t0, v0, t1, v1] of gaps) {
            ctx.moveTo(u.valToPos(t0 / 1000, 'x', true), u.valToPos(v0, 'y', true));
            ctx.lineTo(u.valToPos(t1 / 1000, 'x', true), u.valToPos(v1, 'y', true));
          }
          ctx.stroke();
        });
        ctx.restore();
      },
    },
  };
}

// Shaded time bands under the lines: [{ periods: [[startMs, endMs]], color: '--token', alpha }]
function bandsPlugin(bands) {
  return {
    hooks: {
      drawAxes: (u) => {
        const { ctx } = u;
        const left = u.bbox.left;
        const right = left + u.bbox.width;
        ctx.save();
        for (const b of bands) {
          ctx.fillStyle = token(b.color);
          ctx.globalAlpha = b.alpha ?? 0.14;
          for (const [t0, t1] of b.periods) {
            const x0 = Math.max(left, u.valToPos(t0 / 1000, 'x', true));
            const x1 = Math.min(right, u.valToPos(t1 / 1000, 'x', true));
            if (x1 > x0) ctx.fillRect(x0, u.bbox.top, Math.max(x1 - x0, 1), u.bbox.height);
          }
        }
        ctx.restore();
      },
    },
  };
}

function nowPlugin() {
  // Marks "now" on charts that include forecast hours
  return {
    hooks: {
      draw: (u) => {
        const x = u.valToPos(Date.now() / 1000, 'x', true);
        if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) return;
        const dpr = window.devicePixelRatio || 1;
        const { ctx } = u;
        ctx.save();
        ctx.strokeStyle = token('--axis');
        ctx.lineWidth = dpr;
        ctx.beginPath();
        ctx.moveTo(x, u.bbox.top);
        ctx.lineTo(x, u.bbox.top + u.bbox.height);
        ctx.stroke();
        ctx.fillStyle = token('--text-muted');
        ctx.font = `${11 * dpr}px system-ui, -apple-system, sans-serif`;
        ctx.fillText('now', x + 4 * dpr, u.bbox.top + 12 * dpr);
        ctx.restore();
      },
    },
  };
}

/**
 * series: [{ label, color: '--series-1', points: [[tMs, value|null], ...], dash, gapMs }]
 * options: { unit, decimals, height, threshold: { value, label }, showNow, bands: [{ periods, color, alpha }] }
 * Returns { destroy() }.
 */
export function lineChart(container, series, { unit, decimals = 1, height = 170, threshold, showNow, bands } = {}) {
  const wrap = document.createElement('div');
  wrap.className = 'chart';
  container.appendChild(wrap);

  const split = series.map((s) => splitGaps(s.points, s.gapMs));
  const tables = split.map(({ measured }, i) => {
    const pts = withGaps(measured, series[i].gapMs);
    return [pts.map((p) => p[0] / 1000), pts.map((p) => p[1])];
  });
  // join's default (NULL_RETAIN): our nulls stay gaps; alignment holes between series become undefined and are
  // bridged, so hourly weather and minute readings share one time axis
  const data = tables.length === 1 ? tables[0] : uPlot.join(tables);

  const ink = token('--text-muted');
  const grid = token('--grid');
  const font = '11px system-ui, -apple-system, sans-serif';
  const yRange = threshold
    ? (u, min, max) => uPlot.rangeNum(Math.min(min ?? threshold.value, threshold.value),
      Math.max(max ?? threshold.value, threshold.value), 0.1, true)
    : undefined;

  const chart = new uPlot({
    width: Math.max(200, container.clientWidth),
    height,
    padding: [8, 8, 0, 0],
    scales: { x: { time: true }, y: yRange ? { range: yRange } : {} },
    cursor: { drag: { x: true, y: false }, points: { size: 8 } },
    legend: { live: true },
    series: [
      { value: (u, v) => (v == null ? '–' : clock(v * 1000)) },
      ...series.map((s) => ({
        label: s.label,
        stroke: token(s.color),
        width: 2,
        dash: s.dash,
        points: { show: false },
        value: (u, v) => fmt(v, decimals, unit),
      })),
    ],
    axes: [
      { stroke: ink, font, grid: { stroke: grid, width: 1 }, ticks: { show: false } },
      { stroke: ink, font, size: 52, grid: { stroke: grid, width: 1 }, ticks: { show: false },
        values: (u, vals) => vals.map((v) => `${v}${unit ? ` ${unit}` : ''}`) },
    ],
    plugins: [
      ...(bands?.length ? [bandsPlugin(bands)] : []),
      gapBridgePlugin(split.map((x) => x.gaps), series.map((s) => token(s.color))),
      ...(threshold ? [thresholdPlugin(threshold)] : []),
      ...(showNow ? [nowPlugin()] : []),
    ],
  }, data, wrap);

  // Table view: up to 12 evenly spaced rows, newest first
  const details = document.createElement('details');
  details.className = 'chart-table';
  const n = data[0].length;
  const idx = [];
  for (let k = 0; k < Math.min(12, n); k++) idx.push(n - 1 - Math.round((k * (n - 1)) / Math.max(1, Math.min(12, n) - 1)));
  details.innerHTML = `<summary>Show as table</summary><table><thead><tr><th>Time</th>${
    series.map((s) => `<th>${escapeHtml(s.label)}</th>`).join('')}</tr></thead><tbody>${
    idx.map((i) => `<tr><td>${clock(data[0][i] * 1000)}</td>${
      series.map((_, j) => `<td>${fmt(data[j + 1][i], decimals, unit)}</td>`).join('')}</tr>`).join('')
  }</tbody></table>`;
  container.appendChild(details);

  const ro = new ResizeObserver(() => chart.setSize({ width: Math.max(200, container.clientWidth), height }));
  ro.observe(container);
  return { destroy() { ro.disconnect(); chart.destroy(); wrap.remove(); details.remove(); } };
}
