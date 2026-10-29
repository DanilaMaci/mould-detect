// TV easter egg: a title card, then a drone inspecting a distribution power line, scanning each pole and climbing
// over trees that grow towards the wires. Drawn on a canvas and used as the TV screen texture.
import * as THREE from 'three';

const W = 384;
const H = 216;
const TITLE = 'Dalian presents';
const TITLE_S = 3.5;          // seconds of title card per cycle
const CYCLE_S = 26;
const SPEED = 55;             // px/s the landscape scrolls
const POLE_GAP = 150;         // px between poles
const GROUND = H - 34;
const ARM_Y = 78;             // crossarm height
const SAG = 16;               // wire sag mid-span
const DRONE_X = W * 0.4;

const trees = [];             // world x, height (px), crown radius: some reach the wires
for (let i = 0; i < 40; i++) {
  const x = 80 + i * 97 + ((i * 53) % 40);
  const tall = i % 3 === 1;
  trees.push({ x, top: tall ? 62 + ((i * 17) % 14) : 118 + ((i * 29) % 30), r: tall ? 24 : 16 });
}

const smooth = (x) => x * x * (3 - 2 * x);
const clamp01 = (x) => Math.min(1, Math.max(0, x));

/** Height of the top wire at world x: a parabola between poles (close to a catenary for small sag). */
function wireY(worldX) {
  const u = (((worldX % POLE_GAP) + POLE_GAP) % POLE_GAP) / POLE_GAP;
  return ARM_Y + 4 * SAG * u * (1 - u);
}

export function createTvScreen() {
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext('2d');
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  let t = 0;
  let sinceDraw = 1;
  let droneY = ARM_Y - 26;

  function drawTitle(ct) {
    g.fillStyle = '#05060a';
    g.fillRect(0, 0, W, H);
    const a = smooth(clamp01(ct / 0.8)) * smooth(clamp01((TITLE_S - ct) / 0.8));
    g.globalAlpha = a;
    g.fillStyle = '#f2f2f2';
    g.textAlign = 'center';
    g.font = '600 26px system-ui, -apple-system, sans-serif';
    g.fillText(TITLE, W / 2, H / 2);
    g.fillStyle = '#7dd3fc';
    g.font = '12px ui-monospace, Menlo, monospace';
    g.fillText('autonomous power-line inspection', W / 2, H / 2 + 24);
    g.globalAlpha = 1;
    g.textAlign = 'left';
  }

  function drawFlight(ft, dt) {
    const scroll = ft * SPEED;
    const toScreen = (wx) => wx - scroll;

    // Sky, hills, ground
    const sky = g.createLinearGradient(0, 0, 0, GROUND);
    sky.addColorStop(0, '#7fb8ea');
    sky.addColorStop(1, '#e3f0fa');
    g.fillStyle = sky;
    g.fillRect(0, 0, W, H);
    g.fillStyle = '#a9c99a';
    g.beginPath();
    g.moveTo(0, GROUND);
    for (let x = 0; x <= W; x += 8) g.lineTo(x, GROUND - 26 - 14 * Math.sin((x + scroll * 0.3) / 60));
    g.lineTo(W, GROUND);
    g.fill();
    g.fillStyle = '#6f9f50';
    g.fillRect(0, GROUND, W, H - GROUND);

    // Trees (behind the line)
    for (const tr of trees) {
      const sx = toScreen(tr.x);
      if (sx < -40 || sx > W + 40) continue;
      g.fillStyle = '#6b4a2f';
      g.fillRect(sx - 3, tr.top + tr.r, 6, GROUND - tr.top - tr.r);
      g.fillStyle = '#3f7d3a';
      g.beginPath();
      g.arc(sx, tr.top + tr.r, tr.r, 0, Math.PI * 2);
      g.arc(sx - tr.r * 0.6, tr.top + tr.r * 1.4, tr.r * 0.75, 0, Math.PI * 2);
      g.arc(sx + tr.r * 0.6, tr.top + tr.r * 1.4, tr.r * 0.75, 0, Math.PI * 2);
      g.fill();
    }

    // Poles, crossarms, insulators, three sagging wires
    const first = Math.floor(scroll / POLE_GAP) - 1;
    g.strokeStyle = '#2b2b2b';
    g.lineWidth = 1.2;
    for (let i = first; i < first + 5; i++) {
      const sx = toScreen(i * POLE_GAP);
      g.fillStyle = '#7a6a58';
      g.fillRect(sx - 3, ARM_Y - 6, 6, GROUND - ARM_Y + 6);
      g.fillRect(sx - 18, ARM_Y - 2, 36, 4);
      g.fillStyle = '#cfd8dc';
      for (const dx of [-15, 0, 15]) g.fillRect(sx + dx - 1.5, ARM_Y - 7, 3, 5);
      const nx = toScreen((i + 1) * POLE_GAP);
      for (const dx of [-15, 0, 15]) {
        g.beginPath();
        g.moveTo(sx + dx, ARM_Y - 6);
        g.quadraticCurveTo((sx + nx) / 2 + dx, ARM_Y - 6 + 2 * SAG, nx + dx, ARM_Y - 6);
        g.stroke();
      }
    }

    // Drone follows the line just above it, and climbs when a tree crown is near the path
    const worldX = scroll + DRONE_X;
    let target = wireY(worldX) - 32;
    let avoiding = false;
    for (const tr of trees) {
      if (Math.abs(tr.x - worldX) < 70 && tr.top - 18 < target) {
        target = Math.min(target, tr.top - 18);
        avoiding = true;
      }
    }
    droneY += (target - droneY) * Math.min(1, dt * 3);

    // Scan cone onto the wires, sweeping
    const sweep = Math.sin(ft * 3) * 14;
    g.fillStyle = 'rgba(56, 220, 255, 0.22)';
    g.beginPath();
    g.moveTo(DRONE_X, droneY + 4);
    g.lineTo(DRONE_X - 22 + sweep, wireY(worldX) + 4);
    g.lineTo(DRONE_X + 22 + sweep, wireY(worldX) + 4);
    g.closePath();
    g.fill();

    // Highlight the insulators of the pole being passed
    const nearPole = Math.round(worldX / POLE_GAP) * POLE_GAP;
    if (Math.abs(nearPole - worldX) < 30) {
      g.strokeStyle = '#4ade80';
      g.lineWidth = 1.5;
      g.strokeRect(toScreen(nearPole) - 21, ARM_Y - 11, 42, 12);
    }

    // Quadcopter
    g.fillStyle = '#20232a';
    g.fillRect(DRONE_X - 7, droneY - 3, 14, 6);
    g.fillRect(DRONE_X - 15, droneY - 1, 30, 2);
    g.fillStyle = 'rgba(30, 30, 30, 0.35)';
    for (const dx of [-15, 15]) {
      g.beginPath();
      g.ellipse(DRONE_X + dx, droneY - 3, 9, 1.8, 0, 0, Math.PI * 2);
      g.fill();
    }
    g.fillStyle = Math.sin(ft * 10) > 0 ? '#ef4444' : '#22c55e';
    g.fillRect(DRONE_X + 6, droneY - 1, 2, 2);

    // HUD
    g.font = '10px ui-monospace, Menlo, monospace';
    g.fillStyle = 'rgba(0,0,0,0.45)';
    g.fillRect(6, 6, 170, avoiding ? 40 : 28);
    g.fillStyle = '#e5e7eb';
    g.fillText(`LINE 07 · km ${(worldX / 1000).toFixed(2)}`, 12, 18);
    g.fillText(`poles scanned: ${Math.max(0, Math.floor(worldX / POLE_GAP))}`, 12, 30);
    if (avoiding) {
      g.fillStyle = '#fbbf24';
      g.fillText('VEGETATION ▲ climbing', 12, 42);
    }
    g.fillStyle = '#ef4444';
    g.beginPath();
    g.arc(W - 40, 14, 3.5, 0, Math.PI * 2);
    if (Math.sin(ft * 4) > -0.3) g.fill();
    g.fillStyle = '#e5e7eb';
    g.fillText('REC', W - 32, 18);
  }

  return {
    texture,
    update(dt) {
      t += dt;
      sinceDraw += dt;
      if (sinceDraw < 1 / 30) return;   // 30 fps is plenty for a screen this small
      const ct = t % CYCLE_S;
      if (ct < TITLE_S) drawTitle(ct);
      else drawFlight(ct - TITLE_S, sinceDraw);
      sinceDraw = 0;
      texture.needsUpdate = true;
    },
  };
}
