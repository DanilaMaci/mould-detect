// Layout checks for the room model: furniture inside the room, no overlaps, the robot's loop clear of everything.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ROOM } from '../src/room-model.js';

const L = ROOM.length;
const W = ROOM.width;

// Axis-aligned footprint [x0, x1, z0, z1]; a 90° rotation swaps the two sizes
function footprint({ x, z, size: [sx, sz], rotationY = 0 }) {
  const swap = Math.abs(Math.round(rotationY / (Math.PI / 2))) % 2 === 1;
  const [hx, hz] = swap ? [sz / 2, sx / 2] : [sx / 2, sz / 2];
  return [x - hx, x + hx, z - hz, z + hz];
}

const fireplace = (() => {
  const f = ROOM.rightWall.fireplace;
  return [L / 2 - 0.28, L / 2, f.z - f.width / 2 - 0.08, f.z + f.width / 2 + 0.08];
})();

const boxes = { ...Object.fromEntries(Object.entries(ROOM.furniture).map(([k, v]) => [k, footprint(v)])), fireplace };

test('furniture stays inside the room', () => {
  for (const [name, [x0, x1, z0, z1]] of Object.entries(boxes)) {
    assert.ok(x0 >= -L / 2 && x1 <= L / 2 && z0 >= -W / 2 && z1 <= W / 2, `${name} ${[x0, x1, z0, z1]}`);
  }
});

test('no two pieces overlap', () => {
  const names = Object.keys(boxes);
  for (let i = 0; i < names.length; i++) {
    for (let j = i + 1; j < names.length; j++) {
      const [a, b] = [boxes[names[i]], boxes[names[j]]];
      assert.ok(!(a[0] < b[1] && b[0] < a[1] && a[2] < b[3] && b[2] < a[3]), `${names[i]} overlaps ${names[j]}`);
    }
  }
});

test('balcony-wall openings do not overlap', () => {
  const spans = ROOM.backWall.openings.map((o) => [o.x - o.width / 2, o.x + o.width / 2]).sort((a, b) => a[0] - b[0]);
  // Side panels touch the doors: allow rounding at the shared edge
  for (let i = 1; i < spans.length; i++) assert.ok(spans[i][0] >= spans[i - 1][1] - 1e-9);
});

test('robot loop keeps at least 5 cm from furniture and walls', () => {
  const { center: [cx, cz], radiusX, radiusZ, radius } = ROOM.robot;
  const clearance = (px, pz, [x0, x1, z0, z1]) =>
    Math.hypot(Math.max(x0 - px, 0, px - x1), Math.max(z0 - pz, 0, pz - z1)) - radius;
  for (let k = 0; k < 360; k++) {
    const a = (k / 360) * 2 * Math.PI;
    const px = cx + radiusX * Math.cos(a);
    const pz = cz + radiusZ * Math.sin(a);
    assert.ok(Math.abs(px) + radius <= L / 2 - 0.05 && Math.abs(pz) + radius <= W / 2 - 0.05, `wall at ${k}°`);
    for (const [name, b] of Object.entries(boxes)) assert.ok(clearance(px, pz, b) >= 0.05, `${name} at ${k}°`);
  }
});

test('door swing stays clear of furniture and inside the room', () => {
  const { x, width } = ROOM.door;
  const swing = [x - width / 2, x + width / 2, W / 2 - width, W / 2];   // square the leaf sweeps
  assert.ok(swing[0] >= -L / 2 && swing[1] <= L / 2, 'door within the front wall');
  for (const [name, b] of Object.entries(boxes)) {
    assert.ok(!(swing[0] < b[1] && b[0] < swing[1] && swing[2] < b[3] && b[2] < swing[3]), `door hits ${name}`);
  }
});

test('wall probe sits on the balcony wall, not on the glass', () => {
  // It may sit right at a window's reveal (it does: top corner of the side window), but not inside the opening
  const { x, y } = ROOM.probes.wall;
  assert.ok(Math.abs(x) < L / 2 && y > 0 && y < ROOM.height);
  for (const o of ROOM.backWall.openings) {
    const inX = x > o.x - o.width / 2 && x < o.x + o.width / 2;
    const inY = y > o.sill && y < o.sill + o.height;
    assert.ok(!(inX && inY), `probe inside ${o.id}`);
  }
});

test('radiators stand against the front wall, clear of the door swing and the furniture', () => {
  const { x: dx, width: dw } = ROOM.door;
  for (const r of ROOM.heating.radiators) {
    const rb = [r.x - r.width / 2, r.x + r.width / 2, W / 2 - 0.12, W / 2];
    assert.ok(rb[1] <= dx - dw / 2 || rb[0] >= dx + dw / 2 + 0.3, 'radiator not in the doorway or the glazed panel');
    for (const [name, b] of Object.entries(boxes)) {
      assert.ok(!(rb[0] < b[1] && b[0] < rb[1] && rb[2] < b[3] && b[2] < rb[3]), `radiator hits ${name}`);
    }
  }
});
