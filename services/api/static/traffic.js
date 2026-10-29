// Live traffic page: polls /traffic.json every second and redraws the tiles and two SVG line charts.
// Served from the API itself, so the page's Content-Security-Policy can allow only scripts and requests to 'self'.
const SVG = 'http://www.w3.org/2000/svg';
const $ = (id) => document.getElementById(id);
const fmt = (v) => (v === null || v === undefined ? '–' : String(v));

function line(svg, values, max, color, width) {
  const n = values.length;
  const pts = [];
  values.forEach((v, i) => {
    if (v === null) return;   // no requests that second: leave a gap rather than draw a zero
    pts.push(`${(i / (n - 1)) * 600},${150 - (v / max) * 140}`);
  });
  if (pts.length < 2) return;
  const el = document.createElementNS(SVG, 'polyline');
  el.setAttribute('points', pts.join(' '));
  el.setAttribute('fill', 'none');
  el.setAttribute('stroke', color);
  el.setAttribute('stroke-width', width);
  el.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.appendChild(el);
}

function chart(svg, seriesList, unit) {
  svg.replaceChildren();
  const all = seriesList.flatMap((s) => s.values).filter((v) => v !== null);
  const max = Math.max(1, ...all) * 1.1;
  const label = document.createElementNS(SVG, 'text');
  label.setAttribute('x', 4);
  label.setAttribute('y', 14);
  label.setAttribute('font-size', 12);
  label.setAttribute('fill', 'currentColor');
  label.textContent = `max ${Math.round(max)} ${unit}`;
  svg.appendChild(label);
  for (const s of seriesList) line(svg, s.values, max, s.color, s.width);
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

async function tick() {
  try {
    const res = await fetch('/traffic.json', { cache: 'no-store' });
    const w = await res.json();
    $('rps').textContent = fmt(w.rps);
    $('err').textContent = `${w.error_pct} %`;
    $('err-tile').classList.toggle('bad', w.error_pct > 0);
    $('p50').textContent = fmt(w.p50_ms);
    $('p95').textContent = fmt(w.p95_ms);
    $('p99').textContent = fmt(w.p99_ms);
    $('inflight').textContent = fmt(w.in_flight);
    $('shed').textContent = fmt(w.shed_total);
    $('shed-tile').classList.toggle('bad', w.shed_total > 0);
    const s = w.series;
    chart($('rate-chart'), [
      { values: s.map((p) => p.rps), color: css('--rate'), width: 2 },
      { values: s.map((p) => p.errors), color: css('--err'), width: 2 },
    ], 'req/s');
    chart($('lat-chart'), [
      { values: s.map((p) => p.p50_ms), color: css('--p50'), width: 2 },
      { values: s.map((p) => p.p99_ms), color: css('--p99'), width: 2 },
    ], 'ms');
    const codes = Object.entries(w.status);
    $('codes').replaceChildren(...(codes.length ? codes : [['–', 'no requests in the last 10 s']]).map(([c, n]) => {
      const tr = document.createElement('tr');
      for (const v of [c, n]) {
        const td = document.createElement('td');
        td.textContent = v;   // textContent, never innerHTML: nothing from the server is parsed as HTML
        tr.appendChild(td);
      }
      return tr;
    }));
    $('state').textContent = '';
  } catch (e) {
    $('state').textContent = 'API not answering.';
  }
}

tick();
setInterval(tick, 1000);
