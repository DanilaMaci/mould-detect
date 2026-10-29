// The 3D room: a cutaway diorama (floor + balcony wall + fireplace wall) built from ROOM, set in a small world
// (sky dome, grass, the soccer field behind the balcony) whose sky and precipitation follow the weather. Room air
// tints with CO2 and humidity; sensors are clickable with floating live tags. Easter egg: the LiDAR robot.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { ROOM } from '../room-model.js';
import { sunDirection, sunPosition } from '../sun.js';
import { createTvScreen } from './tv.js';

const COLORS = {
  wall: 0xf1e9dc, plinth: 0xd9cfc0, trim: 0xfbfaf7, curtain: 0x1d2a5c, mantel: 0xb8834a, firebox: 0x2a2826,
  desk: 0xf4f2ee, table: 0xf7f7f5, pcb: 0x1f6f4a, sensorBody: 0x222326, accent: 0x2a78d6, glass: 0xbfd9ee,
  air: 0xffb46b, mote: 0xdfefff, couch: 0xeee3d3, pillow: 0xd99aa5, grass: 0x7ea35a, screen: 0x0d0f14,
};

const DEFAULT_VIEW = { position: [-6.4, 4.8, 7.0], target: [0.7, 0.85, -0.6] };
const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
const v3 = (a) => new THREE.Vector3(...a);

// ---------- textures ----------

function canvasTexture(w, h, draw) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

// Planks run along the canvas x axis, which maps to world x: parallel to the balcony wall
function plankTexture() {
  const t = canvasTexture(512, 512, (g) => {
    for (let r = 0; r < 8; r++) {
      let x = -((r * 173) % 300);
      while (x < 512) {
        const len = 260 + ((r * 97 + x) % 180);
        const shade = 200 + ((r * 31 + Math.abs(x)) % 24);
        g.fillStyle = `rgb(${shade},${shade - 38},${shade - 84})`;
        g.fillRect(x, r * 64, len, 64);
        g.fillStyle = 'rgba(70,45,20,0.35)';
        g.fillRect(x, r * 64, 2, 64);
        x += len;
      }
      g.fillStyle = 'rgba(70,45,20,0.35)';
      g.fillRect(0, r * 64, 512, 2);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(ROOM.length / 2, ROOM.width / 2);
  return t;
}

function rugTexture() {
  return canvasTexture(128, 512, (g) => {
    g.fillStyle = '#111';
    g.fillRect(0, 0, 128, 512);
    g.strokeStyle = '#eee';
    g.lineWidth = 7;
    for (let y = 0; y < 512; y += 64) {
      for (const s of [44, 26, 8]) {
        g.beginPath();
        g.moveTo(64, y + 32 - s); g.lineTo(64 + s, y + 32); g.lineTo(64, y + 32 + s); g.lineTo(64 - s, y + 32);
        g.closePath(); g.stroke();
      }
    }
  });
}

// Repeatable pseudo-random numbers so textures look the same on every load
function seeded(seed) {
  let x = seed;
  return () => { x = (x * 1664525 + 1013904223) % 4294967296; return x / 4294967296; };
}

// Navy curtains with planets and stars, like the real ones
function spaceTexture() {
  return canvasTexture(256, 1024, (g, w, h) => {
    const r = seeded(7);
    g.fillStyle = '#18234f';
    g.fillRect(0, 0, w, h);
    g.fillStyle = 'rgba(255,255,255,0.8)';
    for (let i = 0; i < 160; i++) g.fillRect(r() * w, r() * h, 2, 2);
    const colors = ['#f08a24', '#f5c542', '#3fb6a8', '#e05a2b', '#f2efe6'];
    for (let i = 0; i < 22; i++) {
      const x = r() * w, y = r() * h, rad = 10 + r() * 22;
      g.fillStyle = colors[i % colors.length];
      g.beginPath(); g.arc(x, y, rad, 0, Math.PI * 2); g.fill();
      if (i % 4 === 0) {
        g.strokeStyle = 'rgba(255,220,150,0.8)'; g.lineWidth = 3;
        g.beginPath(); g.ellipse(x, y, rad * 1.7, rad * 0.45, -0.4, 0, Math.PI * 2); g.stroke();
      }
    }
  });
}

// Cream fabric with red flowers on green stems, like the real couch: a regular half-drop repeat (one flower in two
// opposite quarters of the tile, small buds in the other two), drawn inside each quarter so the tile is seamless.
const FABRIC_TILE_M = 0.28;   // one pattern tile on the couch, metres

function floralTexture() {
  const t = canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = '#f3ece0';
    g.fillRect(0, 0, w, h);
    const flower = (x, y) => {
      g.strokeStyle = '#4f7d3a';
      g.lineWidth = 3;
      g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + 6, y + 22, x, y + 44); g.stroke();
      g.fillStyle = '#5f8f45';
      g.beginPath(); g.ellipse(x + 10, y + 24, 9, 4, 0.6, 0, Math.PI * 2); g.fill();
      g.beginPath(); g.ellipse(x - 9, y + 33, 9, 4, -0.6, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#c62f3a';
      for (let k = 0; k < 6; k++) {
        const a = (k / 6) * Math.PI * 2;
        g.beginPath(); g.arc(x + Math.cos(a) * 9, y + Math.sin(a) * 9, 7.5, 0, Math.PI * 2); g.fill();
      }
      g.fillStyle = '#7d1620';
      g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.fill();
    };
    const bud = (x, y) => {
      g.fillStyle = '#d9727b';
      g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#5f8f45';
      g.beginPath(); g.ellipse(x, y + 9, 6, 2.5, 0, 0, Math.PI * 2); g.fill();
    };
    flower(w * 0.25, h * 0.2);
    flower(w * 0.75, h * 0.7);
    bud(w * 0.75, h * 0.25);
    bud(w * 0.25, h * 0.75);
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

// White disc fading to transparent at the edge: tinted per use (wall humidity patch)
function radialTexture() {
  return canvasTexture(128, 128, (g, w, h) => {
    const grad = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.55, 'rgba(255,255,255,0.55)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
  });
}

// Mould speckles: dark grey-green spots, densest in the middle, fading out (opacity follows hours of high humidity)
function mouldTexture() {
  return canvasTexture(256, 256, (g, w, h) => {
    const r = seeded(23);
    for (let i = 0; i < 900; i++) {
      const a = r() * Math.PI * 2;
      const d = Math.sqrt(r()) * w * 0.46 * (0.4 + 0.6 * r());
      const x = w / 2 + Math.cos(a) * d;
      const y = h / 2 + Math.sin(a) * d;
      const fade = 1 - d / (w * 0.46);
      g.fillStyle = `rgba(${40 + r() * 25}, ${52 + r() * 20}, ${38 + r() * 15}, ${0.25 + 0.6 * fade * r()})`;
      g.beginPath(); g.arc(x, y, 1 + r() * 3.5 * fade, 0, Math.PI * 2); g.fill();
    }
  });
}

// The desk monitor's idle screen: an invitation to replay the last 24 hours
function idleScreenTexture() {
  return canvasTexture(512, 288, (g, w, h) => {
    const grad = g.createLinearGradient(0, 0, w, h);
    grad.addColorStop(0, '#0f1b2d');
    grad.addColorStop(1, '#1d3b5c');
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.fillStyle = '#2a78d6';
    g.beginPath(); g.arc(w / 2, h / 2 - 22, 46, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#ffffff';
    g.beginPath(); g.moveTo(w / 2 - 14, h / 2 - 48); g.lineTo(w / 2 + 24, h / 2 - 22); g.lineTo(w / 2 - 14, h / 2 + 4); g.closePath(); g.fill();
    g.font = '600 30px system-ui, sans-serif';
    g.textAlign = 'center';
    g.fillText('Replay the last 24 h', w / 2, h / 2 + 62);
    g.font = '20px system-ui, sans-serif';
    g.fillStyle = 'rgba(255,255,255,0.7)';
    g.fillText('click the screen', w / 2, h / 2 + 94);
  });
}

// Mown stripes and the standard markings (1 px = 10 cm of a 105 x 68 m pitch)
function pitchTexture() {
  return canvasTexture(1050, 680, (g, w, h) => {
    for (let i = 0; i < 14; i++) {
      g.fillStyle = i % 2 ? '#4f9a3c' : '#58a644';
      g.fillRect((i * w) / 14, 0, w / 14 + 1, h);
    }
    g.strokeStyle = 'rgba(255,255,255,0.9)';
    g.lineWidth = 5;
    const m = 20;
    g.strokeRect(m, m, w - 2 * m, h - 2 * m);
    g.beginPath(); g.moveTo(w / 2, m); g.lineTo(w / 2, h - m); g.stroke();
    g.beginPath(); g.arc(w / 2, h / 2, 91.5, 0, Math.PI * 2); g.stroke();
    for (const side of [0, 1]) {
      const x = side ? w - m : m;
      const dir = side ? -1 : 1;
      g.strokeRect(Math.min(x, x + dir * 165), h / 2 - 201.5, 165, 403);   // penalty area
      g.strokeRect(Math.min(x, x + dir * 55), h / 2 - 91.5, 55, 183);      // goal area
    }
  });
}

function paintSky(canvas, top, horizon) {
  const g = canvas.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 0, canvas.height);
  grad.addColorStop(0, top);
  grad.addColorStop(0.5, horizon);
  grad.addColorStop(1, horizon);
  g.fillStyle = grad;
  g.fillRect(0, 0, canvas.width, canvas.height);
}

/** Sky look and outdoor light for an Open-Meteo WMO weather code. */
export function skyFor(code, isDay) {
  const precip = code >= 71 && code <= 77 || code === 85 || code === 86 ? 'snow'
    : (code >= 51 && code <= 67) || (code >= 80 && code <= 82) || code >= 95 ? 'rain' : null;
  const fog = code === 45 || code === 48;
  const overcast = code >= 3;
  if (!isDay) return { top: '#0b1229', bottom: '#28324f', sun: 0.15, sunColor: 0x8fa3d9, precip, fog };
  if (fog) return { top: '#c4c9cf', bottom: '#e3e5e7', sun: 0.8, sunColor: 0xf2f2f2, precip, fog };
  if (precip) return { top: '#76818e', bottom: '#b6bec6', sun: 0.9, sunColor: 0xdfe6ee, precip, fog };
  if (overcast) return { top: '#97aabd', bottom: '#dde4ea', sun: 1.4, sunColor: 0xf3f1ea, precip, fog };
  return { top: '#4f9be6', bottom: '#d3eaff', sun: 2.6, sunColor: 0xfff1d6, precip, fog };
}

// ---------- geometry helpers ----------

function box(w, h, d, color, opts = {}) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
    new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...opts }));
  m.castShadow = m.receiveShadow = true;
  return m;
}

const at = (obj, x, y, z) => { obj.position.set(x, y, z); return obj; };

/**
 * A box whose texture repeats every `tile` metres on every face, so a pattern has the same size and orientation
 * on all parts of a piece of furniture (BoxGeometry maps the whole texture onto each face by default).
 */
function fabricBox(w, h, d, material, tile) {
  const geo = new THREE.BoxGeometry(w, h, d);
  const uv = geo.attributes.uv;
  // Face order in BoxGeometry: +x, -x, +y, -y, +z, -z; 4 vertices each. [u extent, v extent] per face:
  const extents = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let face = 0; face < 6; face++) {
    const [eu, ev] = extents[face];
    for (let k = 0; k < 4; k++) {
      const i = face * 4 + k;
      uv.setXY(i, (uv.getX(i) * eu) / tile, (uv.getY(i) * ev) / tile);
    }
  }
  const m = new THREE.Mesh(geo, material);
  m.castShadow = m.receiveShadow = true;
  return m;
}

/** A wall along local x (length L, centred), with rectangular openings { center, width, height, sill }. */
function wallWithOpenings(L, H, T, openings, material) {
  const g = new THREE.Group();
  const add = (x0, x1, y0, y1) => {
    if (x1 - x0 < 1e-3 || y1 - y0 < 1e-3) return;
    const m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, y1 - y0, T), material);
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, 0);
    m.castShadow = m.receiveShadow = true;
    g.add(m);
  };
  let x = -L / 2;
  for (const o of [...openings].sort((a, b) => a.center - b.center)) {
    const a = o.center - o.width / 2;
    const b = o.center + o.width / 2;
    add(x, a, 0, H);
    add(a, b, o.sill + o.height, H);
    add(a, b, 0, o.sill);
    x = b;
  }
  add(x, L / 2, 0, H);
  return g;
}

/** Frame and glass for an opening in a wall built by wallWithOpenings (same local axes). */
function glazing(o, T, leaves, glass) {
  const g = new THREE.Group();
  const frame = new THREE.MeshStandardMaterial({ color: COLORS.trim, roughness: 0.5 });
  const f = 0.06;
  const piece = (w, h, x, y) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, T * 0.6), frame);
    m.position.set(x, y, 0);
    m.castShadow = true;
    g.add(m);
  };
  const x0 = o.center - o.width / 2;
  const y0 = o.sill;
  piece(o.width, f, o.center, y0 + o.height - f / 2);
  piece(o.width, f, o.center, y0 + f / 2);
  const leafW = o.width / leaves;
  for (let i = 0; i <= leaves; i++) piece(f, o.height, x0 + i * leafW + (i === 0 ? f / 2 : i === leaves ? -f / 2 : 0), y0 + o.height / 2);
  for (let i = 0; i < leaves; i++) {
    const pane = new THREE.Mesh(new THREE.PlaneGeometry(leafW - f * 1.5, o.height - f * 2), glass);
    pane.position.set(x0 + (i + 0.5) * leafW, y0 + o.height / 2, 0);
    g.add(pane);
  }
  if (o.handle) {
    const hx = o.center + (o.handle === 'left' ? -1 : 1) * (o.width / 2 - f * 1.6);
    const handle = new THREE.Mesh(new THREE.BoxGeometry(0.025, 0.14, 0.03), frame);
    handle.position.set(hx, y0 + o.height / 2, T * 0.3 + 0.015);
    g.add(handle);
  }
  return g;
}

function guitar(bodyColor, acoustic) {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: bodyColor, roughness: 0.35 });
  const lower = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat);
  lower.scale.set(0.19, 0.2, 0.05);
  lower.position.y = 0.24;
  const upper = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 16), mat);
  upper.scale.set(0.15, 0.15, 0.05);
  upper.position.y = 0.48;
  for (const m of [lower, upper]) m.castShadow = true;
  g.add(lower, upper,
    at(box(0.05, 0.5, 0.025, 0x3b2a1c, { roughness: 0.6 }), 0, 0.85, 0),    // neck
    at(box(0.08, 0.17, 0.03, 0x241a12, { roughness: 0.6 }), 0, 1.18, 0));   // head
  if (acoustic) {
    g.add(at(new THREE.Mesh(new THREE.CircleGeometry(0.05, 24), new THREE.MeshBasicMaterial({ color: 0x1a120c })), 0, 0.4, 0.051));
  }
  return g;
}

// IKEA Poäng-style lounge chair: bentwood side frames and a cantilevered seat/back shell. Faces -z.
function poangChair() {
  const g = new THREE.Group();
  const birch = new THREE.MeshStandardMaterial({ color: 0xdcbf8f, roughness: 0.5 });
  const fabric = new THREE.MeshStandardMaterial({ color: 0xcbbfa8, roughness: 1 });
  const tube = (pts, r) => {
    const m = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 48, r, 8, false), birch);
    m.castShadow = true;
    return m;
  };
  // Side frames: floor runner curving up into the armrest
  const side = [[0.36, 0.02], [-0.3, 0.02], [-0.4, 0.1], [-0.37, 0.4], [-0.22, 0.55], [0.1, 0.5], [0.22, 0.38]];
  for (const sx of [-1, 1]) g.add(tube(side.map(([z, y]) => new THREE.Vector3(sx * 0.3, y, z)), 0.018));
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.6), birch);
  bar.rotation.z = Math.PI / 2;
  g.add(at(bar, 0, 0.03, 0.34));
  // Seat and back: one bent shell, the cushion built from short segments along it
  const shellPts = [[-0.37, 0.42], [-0.12, 0.33], [0.12, 0.36], [0.26, 0.55], [0.36, 0.95]];
  const shell = new THREE.CatmullRomCurve3(shellPts.map(([z, y]) => new THREE.Vector3(0, y, z)));
  const N = 16;
  for (let i = 0; i < N; i++) {
    const p0 = shell.getPoint(i / N);
    const p1 = shell.getPoint((i + 1) / N);
    const seg = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.07, p0.distanceTo(p1) + 0.012), fabric);
    seg.position.copy(p0).add(p1).multiplyScalar(0.5);
    seg.rotation.x = -Math.atan2(p1.y - p0.y, p1.z - p0.z);
    seg.castShadow = true;
    g.add(seg);
  }
  for (const sx of [-1, 1]) g.add(tube(shellPts.map(([z, y]) => new THREE.Vector3(sx * 0.25, y - 0.05, z)), 0.014));
  return g;
}

// ---------- scene ----------

/**
 * container: element to render into. onSelect(hotspotId): a sensor was clicked. location: { lat, lon } in degrees
 * for the sun's path (rounded is fine; the demo uses a neutral default).
 */
export function createRoomScene(container, { onSelect, onComputer, location = { lat: 52, lon: 0 } } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;
  container.appendChild(renderer.domElement);

  const labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.className = 'scene-labels';
  container.appendChild(labelRenderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xdde4ea, 22, 70);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 160);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, {
    enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 1.5, maxDistance: 20,
    maxPolarAngle: 1.42, minAzimuthAngle: -1.8, maxAzimuthAngle: 0.35, rotateSpeed: 0.6,
  });

  const L = ROOM.length, W = ROOM.width, H = ROOM.height, T = ROOM.wallThickness;
  const back = -W / 2, right = L / 2;
  const F = ROOM.furniture;
  const lidarTargets = [];   // what the robot's LiDAR can hit
  const place = (obj, f) => {
    obj.position.set(f.x, 0, f.z);
    obj.rotation.y = f.rotationY ?? 0;
    scene.add(obj);
    lidarTargets.push(obj);
    return obj;
  };

  // Lights: sky/ground fill, daylight from behind the balcony wall, warm ceiling light
  const hemi = new THREE.HemisphereLight(0xffffff, 0xcdbf9f, 1.6);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xfff1d6, 2.2);
  sun.position.set(-1.5, 7, back - 9);
  sun.target.position.set(0, 0, 0.3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 1, far: 30 });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, sun.target);
  let baseSun = 2.2;        // weather's sunlight; scaled by the sun's elevation each frame
  let sceneTime = null;     // null = live (now); a timestamp during replay
  const lamp = new THREE.PointLight(0xffd6a0, 6, 12, 2);
  lamp.position.set(0, H - 0.15, 0);
  scene.add(lamp);

  // ----- world: sky dome, grass, soccer field behind the balcony -----
  const skyCanvas = document.createElement('canvas');
  skyCanvas.width = 4; skyCanvas.height = 256;
  paintSky(skyCanvas, '#97aabd', '#dde4ea');
  const skyTex = new THREE.CanvasTexture(skyCanvas);
  skyTex.colorSpace = THREE.SRGBColorSpace;
  const sky = new THREE.Mesh(new THREE.SphereGeometry(75, 32, 16),
    new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide, fog: false, depthWrite: false }));
  sky.raycast = () => {};
  scene.add(sky);

  const GROUND = -0.95;
  const ground = new THREE.Mesh(new THREE.CircleGeometry(75, 48),
    new THREE.MeshStandardMaterial({ color: COLORS.grass, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = GROUND;
  ground.receiveShadow = true;
  scene.add(ground);

  const pitchZ = back - 13;
  const pitch = new THREE.Mesh(new THREE.PlaneGeometry(28, 18),
    new THREE.MeshStandardMaterial({ map: pitchTexture(), roughness: 1, polygonOffset: true,
      polygonOffsetFactor: -1, polygonOffsetUnits: -1 }));
  pitch.rotation.x = -Math.PI / 2;
  pitch.position.set(0, GROUND, pitchZ);
  pitch.receiveShadow = true;
  scene.add(pitch);
  const goalMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4 });
  for (const side of [-1, 1]) {
    const gx = side * 13.45;
    for (const dz of [-0.98, 0.98]) {
      const post = at(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.65, 0.06), goalMat), gx, GROUND + 0.325, pitchZ + dz);
      post.castShadow = true;
      scene.add(post);
    }
    scene.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 2.02), goalMat), gx, GROUND + 0.65, pitchZ));
  }

  // ----- plinth, floor -----
  // Plinth under the room, ending at the balcony wall so it never overlaps the balcony slab
  const pz0 = back - T;
  const pz1 = W / 2 + 0.45;
  scene.add(at(box(L + 0.6, -GROUND - 0.02, pz1 - pz0, COLORS.plinth, { roughness: 1 }), 0, (GROUND - 0.02) / 2, (pz0 + pz1) / 2));
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(L, W),
    new THREE.MeshStandardMaterial({ map: plankTexture(), roughness: 0.75 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  // ----- walls: balcony wall (back) and fireplace wall (right) -----
  const wallMat = new THREE.MeshStandardMaterial({ color: COLORS.wall, roughness: 0.95 });
  const openings = ROOM.backWall.openings.map((o) => ({ ...o, center: o.x }));
  // One glass material for every pane: it mists up when the glass is near the dew point (setGlass)
  const GLASS_CLEAR = new THREE.Color(COLORS.glass);
  const GLASS_FOGGED = new THREE.Color(0xf2f5f7);
  const glassMat = new THREE.MeshStandardMaterial({ color: COLORS.glass, roughness: 0.05, metalness: 0.1,
    transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide });
  let fog = 0;
  let fogShown = 0;
  const backWall = at(wallWithOpenings(L, H, T, openings, wallMat), 0, 0, back - T / 2);
  scene.add(backWall);
  scene.add(at(box(T, H, T, COLORS.wall, { roughness: 0.95 }), right + T / 2, H / 2, back - T / 2));   // corner

  const rightWall = wallWithOpenings(W, H, T, [], wallMat);
  rightWall.rotation.y = -Math.PI / 2;
  scene.add(at(rightWall, right + T / 2, 0, 0));
  lidarTargets.push(backWall, rightWall);

  scene.add(at(box(L, 0.08, 0.02, COLORS.trim), 0, 0.04, back + 0.01));      // skirting
  scene.add(at(box(0.02, 0.08, W, COLORS.trim), right - 0.01, 0.04, 0));

  // ----- balcony doors and side windows (clickable: outdoor weather), curtains, rug-covered narrow window -----
  const outdoorGroup = new THREE.Group();
  outdoorGroup.userData.hotspot = 'outdoor';
  const doors = openings.find((o) => o.id === 'frenchDoors');
  const screenParts = [openings.find((o) => o.id === 'sideWindowLeft'), doors, openings.find((o) => o.id === 'sideWindowRight')]
    .filter(Boolean);
  // Side panels: fixed lower pane, and an upper casement on a hinge opposite its handle that swings into the room
  // when the window button says "open"
  const sashes = [];
  for (const o of screenParts) {
    if (!o.split) {
      outdoorGroup.add(at(glazing(o, T, o === doors ? 2 : 1, glassMat), 0, 0, back - T / 2));
      continue;
    }
    outdoorGroup.add(at(glazing({ ...o, height: o.split, handle: undefined }, T, 1, glassMat), 0, 0, back - T / 2));
    const hingeX = o.handle === 'left' ? o.center + o.width / 2 : o.center - o.width / 2;
    const pivot = at(new THREE.Group(), hingeX, 0, back - T / 2);
    pivot.add(at(glazing({ ...o, sill: o.split, height: o.height - o.split }, T, 1, glassMat), -hingeX, 0, 0));
    pivot.userData.swing = o.handle === 'left' ? 1 : -1;   // sign of rotation.y that moves the free edge inwards
    pivot.userData.interact = 'window';
    pivot.userData.span = [o.center - o.width / 2, o.center + o.width / 2, o.split, o.height];
    outdoorGroup.add(pivot);
    sashes.push(pivot);
  }
  scene.add(outdoorGroup);
  // Curtains, rail and vent follow the whole glazed screen, not just the doors
  const screenL = Math.min(...screenParts.map((o) => o.x - o.width / 2));
  const screenR = Math.max(...screenParts.map((o) => o.x + o.width / 2));
  const screen = { x: (screenL + screenR) / 2, width: screenR - screenL };
  lidarTargets.push(outdoorGroup);

  // Invisible bounds on the two cut-away sides: the LiDAR scans the room, not the world beyond
  const boundMat = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
  const leftBound = new THREE.Mesh(new THREE.PlaneGeometry(W, H), boundMat);
  leftBound.rotation.y = Math.PI / 2;
  const frontBound = new THREE.Mesh(new THREE.PlaneGeometry(L, H), boundMat);
  scene.add(at(leftBound, -L / 2, H / 2, 0), at(frontBound, 0, H / 2, W / 2));
  lidarTargets.push(leftBound, frontBound);

  const curtainTex = spaceTexture();
  for (const side of [-1, 1]) {
    scene.add(at(box(0.32, 2.2, 0.08, 0xffffff, { roughness: 1, map: curtainTex }), screen.x + side * (screen.width / 2 + 0.12), 1.12, back + 0.06));
  }
  // Wall vent near the ceiling, right of the screen
  const vent = new THREE.Group();
  vent.add(box(0.3, 0.13, 0.015, COLORS.trim, { roughness: 0.6 }));
  for (let i = -1.5; i <= 1.5; i++) vent.add(at(box(0.26, 0.012, 0.004, 0x9c9a94), 0, i * 0.028, 0.009));
  scene.add(at(vent, screenR + 0.45, 2.18, back + 0.01));
  const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, screen.width + 0.7),
    new THREE.MeshStandardMaterial({ color: 0xb9bcc2, metalness: 0.8, roughness: 0.3 }));
  rail.rotation.z = Math.PI / 2;
  scene.add(at(rail, screen.x, 2.24, back + 0.06));

  const narrow = openings.find((o) => o.id === 'narrowWindow');
  if (narrow) {
    const narrowGlass = at(glazing(narrow, T, 1, glassMat), 0, 0, back - T / 2);
    scene.add(narrowGlass);
    lidarTargets.push(narrowGlass);
    if (narrow.coveredByRug) {
      const rug = new THREE.Mesh(new THREE.PlaneGeometry(narrow.width + 0.08, narrow.height + 0.1),
        new THREE.MeshStandardMaterial({ map: rugTexture(), roughness: 1, side: THREE.DoubleSide }));
      rug.castShadow = true;
      scene.add(at(rug, narrow.x, narrow.sill + narrow.height / 2, back + 0.03));
    }
  }

  // ----- fireplace in the middle of the fireplace wall -----
  const fp = ROOM.rightWall.fireplace;
  const mantel = at(box(0.22, fp.height, fp.width, COLORS.mantel, { roughness: 0.6 }), right - 0.11, fp.height / 2, fp.z);
  scene.add(mantel);
  lidarTargets.push(mantel);
  scene.add(at(box(0.02, fp.height * 0.6, fp.width * 0.62, COLORS.firebox, { roughness: 0.4 }), right - 0.225, fp.height * 0.33, fp.z));
  scene.add(at(box(0.28, 0.05, fp.width + 0.16, COLORS.mantel, { roughness: 0.6 }), right - 0.14, fp.height + 0.025, fp.z));

  // ----- two guitars left of the balcony doors, leaning on the wall -----
  for (const [dx, color, acoustic] of [[-0.18, 0xc58b4e, true], [0.2, 0x8b1e2b, false]]) {
    const gtr = at(guitar(color, acoustic), F.guitars.x + dx, 0.02, F.guitars.z);
    gtr.rotation.set(-0.16, dx * 0.6, 0);
    scene.add(gtr);
    lidarTargets.push(gtr);
  }

  // ----- couch opposite the fireplace, facing the media table (TV + PS5) -----
  // Parts meet edge to edge and never share a visible plane (shared planes flicker as the camera moves)
  const fabric = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, map: floralTexture() });
  const [cw, cd] = F.couch.size;
  const legH = 0.07, armW = 0.18, backD = 0.2, innerW = cw - 2 * armW;
  const couch = new THREE.Group();
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    couch.add(at(box(0.05, legH, 0.05, 0x3a2a1c, { roughness: 0.6 }), sx * (cw / 2 - 0.07), legH / 2, sz * (cd / 2 - 0.07)));
  }
  const baseTop = 0.42;
  couch.add(at(fabricBox(innerW, baseTop - legH, cd - backD, fabric, FABRIC_TILE_M), 0, (legH + baseTop) / 2, -backD / 2));
  couch.add(at(fabricBox(innerW, 0.86 - legH, backD, fabric, FABRIC_TILE_M), 0, (legH + 0.86) / 2, cd / 2 - backD / 2));
  for (const s of [-1, 1]) {
    couch.add(at(fabricBox(armW, 0.62 - legH, cd, fabric, FABRIC_TILE_M), s * (cw / 2 - armW / 2), (legH + 0.62) / 2, 0));
  }
  // Two seat cushions with a small gap, resting on the base
  const cushW = innerW / 2 - 0.01;
  for (const s of [-1, 1]) {
    couch.add(at(fabricBox(cushW, 0.1, cd - backD - 0.03, fabric, FABRIC_TILE_M), s * (cushW / 2 + 0.005), baseTop + 0.052, -backD / 2 - 0.015));
  }
  for (const px of [-0.6, 0.6]) {
    couch.add(at(box(0.36, 0.3, 0.12, COLORS.pillow, { roughness: 1 }), px, 0.675, cd / 2 - backD - 0.065));
  }
  couch.userData.interact = 'couch';
  place(couch, F.couch);

  const [mw, md] = F.mediaTable.size;
  const media = new THREE.Group();
  media.add(at(box(mw, 0.04, md, COLORS.table, { roughness: 0.5 }), 0, 0.7, 0));
  for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    media.add(at(box(0.035, 0.68, 0.035, 0xdedcd8), dx * (mw / 2 - 0.05), 0.34, dz * (md / 2 - 0.05)));
  }
  const tv = createTvScreen();   // easter egg: the drone inspection film
  media.add(at(box(0.84, 0.5, 0.04, 0x15171c, { roughness: 0.4 }), 0, 1.02, -0.12));          // TV
  media.add(at(new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.46), new THREE.MeshBasicMaterial({ map: tv.texture, toneMapped: false })), 0, 1.02, -0.099));
  media.add(at(box(0.18, 0.04, 0.12, 0x15171c), 0, 0.74, -0.12));                             // TV foot
  media.add(at(box(0.1, 0.39, 0.26, 0xf4f4f2, { roughness: 0.3 }), 0.55, 0.915, -0.05));       // PS5
  media.add(at(box(0.104, 0.37, 0.06, 0x15171c), 0.55, 0.915, -0.05));
  media.add(at(box(0.07, 0.12, 0.07, 0xd9dde3, { roughness: 0.3 }), -0.45, 0.78, 0.12));      // cans
  media.add(at(box(0.07, 0.12, 0.07, 0xc8102e, { roughness: 0.3 }), -0.35, 0.78, 0.16));
  place(media, F.mediaTable);

  // ----- IKEA desk in the corner, facing the balcony, with a 5-shelf unit on its right -----
  const d = F.desk;
  const [dw, dd] = d.size;
  const shelfW = 0.4;
  const topW = dw - shelfW;
  const topX = -dw / 2 + topW / 2;           // desktop centre, local
  const shelfX = dw / 2 - shelfW / 2;        // shelf unit centre, local
  const deskTopX = d.x + topX;               // desktop centre, world
  const desk = new THREE.Group();
  desk.add(at(box(topW, 0.04, dd, COLORS.desk, { roughness: 0.5 }), topX, 0.74, 0));
  for (const dz of [-1, 1]) desk.add(at(box(0.04, 0.72, 0.04, 0xcfcac2), -dw / 2 + 0.04, 0.36, dz * (dd / 2 - 0.04)));
  // Shelf unit under the desktop's end: desk height, its top board flush with the desktop (0.76 m)
  const shelfH = 0.76;
  const board = (i) => 0.01 + i * 0.185;   // board centres: 0.01 … 0.75, top surface 0.76
  for (const sx of [-1, 1]) desk.add(at(box(0.02, shelfH - 0.02, dd, COLORS.desk, { roughness: 0.5 }), shelfX + sx * (shelfW / 2 - 0.01), shelfH / 2 - 0.01, 0));
  desk.add(at(box(shelfW - 0.04, shelfH - 0.04, 0.01, 0xe9e6e0), shelfX, shelfH / 2, -dd / 2 + 0.005));
  for (let i = 0; i < 5; i++) {
    const wBoard = i === 4 ? shelfW : shelfW - 0.04;   // the top board covers the side panels like the desktop
    desk.add(at(box(wBoard, 0.02, dd - (i === 4 ? 0 : 0.02), COLORS.desk, { roughness: 0.5 }), shelfX, board(i), 0));
  }
  // Things on the shelves: component boxes, a filament spool, a few books
  desk.add(at(box(0.16, 0.08, 0.2, 0x3b82f6), shelfX - 0.07, board(1) + 0.01 + 0.04, 0.05));
  desk.add(at(box(0.12, 0.06, 0.16, 0xf59e0b), shelfX + 0.09, board(1) + 0.01 + 0.03, -0.05));
  const spool = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.06, 24), new THREE.MeshStandardMaterial({ color: 0x22c55e, roughness: 0.6 }));
  spool.rotation.x = Math.PI / 2;
  desk.add(at(spool, shelfX, board(2) + 0.01 + 0.07, 0.05));
  for (let i = 0; i < 4; i++) desk.add(at(box(0.03, 0.15, 0.17, [0x1e3a5f, 0x9f1239, 0x334155, 0xca8a04][i]), shelfX - 0.12 + i * 0.035, board(3) + 0.01 + 0.075, 0));
  // Monitor on an arm, breadboard and boards on the desktop
  desk.add(at(box(0.04, 0.28, 0.04, 0x2a2b2f), topX, 0.9, -dd / 2 + 0.08));
  // The monitor is the replay button: click it and the camera zooms in while its screen shows the room's last 24 h
  const monitor = at(box(0.62, 0.37, 0.03, 0x15171c, { roughness: 0.4 }), topX, 1.12, -dd / 2 + 0.11);
  const idleScreen = idleScreenTexture();
  const screenMat = new THREE.MeshBasicMaterial({ map: idleScreen, toneMapped: false });
  const monitorScreen = at(new THREE.Mesh(new THREE.PlaneGeometry(0.58, 0.33), screenMat), topX, 1.12, -dd / 2 + 0.126);
  monitor.userData.interact = monitorScreen.userData.interact = 'computer';
  desk.add(monitor, monitorScreen);
  desk.add(at(box(0.17, 0.012, 0.055, 0xf2f0ea), topX + 0.25, 0.766, 0.12));    // breadboard
  desk.add(at(box(0.05, 0.01, 0.07, 0x1f4fa8), topX + 0.25, 0.775, 0.12));      // board on the breadboard
  desk.add(at(box(0.045, 0.01, 0.06, 0x14532d), topX - 0.35, 0.766, -0.05));    // spare boards
  place(desk, F.desk);

  // Wall socket, extension strip on the floor, and cables up to the desk
  const socketX = d.x - dw / 2 + 0.18;
  scene.add(at(box(0.08, 0.08, 0.01, 0xf5f5f2, { roughness: 0.4 }), socketX, 0.3, back + 0.005));
  const stripPos = new THREE.Vector3(deskTopX + 0.05, 0.02, back + 0.3);
  scene.add(at(box(0.32, 0.04, 0.06, 0xf5f5f2, { roughness: 0.4 }), stripPos.x, stripPos.y, stripPos.z));
  scene.add(at(box(0.03, 0.015, 0.025, 0xf97316), stripPos.x - 0.13, 0.045, stripPos.z));   // switch
  const cable = (pts, color) => {
    const m = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map((q) => new THREE.Vector3(...q))), 40, 0.005, 6, false),
      new THREE.MeshStandardMaterial({ color, roughness: 0.6 }));
    m.castShadow = true;
    scene.add(m);
  };
  const sp = [stripPos.x, 0.03, stripPos.z];
  cable([[socketX, 0.27, back + 0.012], [socketX, 0.03, back + 0.03], [socketX + 0.1, 0.01, back + 0.2], [sp[0] - 0.16, 0.02, sp[2]]], 0xf5f5f2);
  cable([[sp[0] - 0.05, 0.03, sp[2]], [sp[0] - 0.1, 0.1, back + 0.06], [deskTopX, 0.5, back + 0.05], [deskTopX, 0.95, back + 0.09]], 0x1a1a1a);   // monitor
  cable([[sp[0], 0.03, sp[2]], [sp[0] - 0.15, 0.2, back + 0.25], [deskTopX - 0.35, 0.7, back + 0.33], [deskTopX - 0.25, 0.77, d.z + 0.05]], 0x2b2b2b);   // room node USB
  cable([[sp[0] + 0.06, 0.03, sp[2]], [sp[0] + 0.2, 0.15, back + 0.2], [deskTopX + 0.3, 0.72, back + 0.25], [deskTopX + 0.25, 0.77, d.z + 0.1]], 0x2b2b2b);  // breadboard

  place(poangChair(), F.chair);

  // Small wooden table with the 3D printer, beside the fireplace
  const st = F.sideTable;
  const side = new THREE.Group();
  side.add(at(box(st.size[0], 0.04, st.size[1], 0x6b4a2f, { roughness: 0.6 }), 0, 0.6, 0));
  for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    side.add(at(box(0.035, 0.58, 0.035, 0x5a3d26), dx * (st.size[0] / 2 - 0.04), 0.29, dz * (st.size[1] / 2 - 0.04)));
  }
  const alu = { metalness: 0.5, roughness: 0.4 };
  side.add(at(box(0.36, 0.06, 0.34, 0xeeeeec, { roughness: 0.4 }), 0, 0.65, 0));     // printer base
  side.add(at(box(0.26, 0.01, 0.26, 0x2b2d31), 0, 0.685, 0));                        // bed
  for (const sx of [-1, 1]) side.add(at(box(0.03, 0.42, 0.03, 0xb7babf, alu), sx * 0.16, 0.89, 0.12));
  side.add(at(box(0.35, 0.04, 0.04, 0xb7babf, alu), 0, 1.0, 0.12));                 // gantry
  side.add(at(box(0.05, 0.06, 0.05, 0x2b2d31), 0.04, 0.96, 0.09));                  // print head
  place(side, st);

  const hotspotMeshes = [outdoorGroup];   // the robot joins below
  // Things you can click to play with (userData.interact): door, windows, glass, radiator, couch, computer
  const interactables = [couch, desk];
  const glowMats = {};
  const ledMat = (color) => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 2.2 });
  const halo = (r) => new THREE.Mesh(new THREE.SphereGeometry(r, 24, 16),
    new THREE.MeshBasicMaterial({ color: COLORS.accent, transparent: true, opacity: 0.12, depthWrite: false }));

  function sensorGroup(id, parts, position) {
    const g = new THREE.Group();
    g.userData.hotspot = id;
    for (const p of parts) g.add(p);
    g.position.set(...position);
    hotspotMeshes.push(g);
    scene.add(g);
  }

  // Room node: ESP32 board with the BME280 breakout; SCD-40 next to it
  const nodeHalo = halo(0.11);
  // Advice LED on the room node: lights up when the windows should be opened (real LED planned on GPIO23)
  const adviceLedMat = new THREE.MeshStandardMaterial({ color: 0x5a3a10, emissive: 0xffa31a, emissiveIntensity: 0 });
  const adviceGlow = new THREE.Mesh(new THREE.SphereGeometry(0.035, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xffa31a, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
  let adviceOn = false;
  // Window (red) and door (yellow) LEDs, like the real ones on GPIO27/32: lit = open
  const stateLed = (color) => ({
    mat: new THREE.MeshStandardMaterial({ color: 0x3a2a20, emissive: color, emissiveIntensity: 0 }),
    glow: new THREE.Mesh(new THREE.SphereGeometry(0.028, 16, 12), new THREE.MeshBasicMaterial({ color, transparent: true,
      opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending })),
  });
  const windowLed = stateLed(0xff3b30);
  const doorLed = stateLed(0xffc21a);
  sensorGroup('climate', [
    at(new THREE.Mesh(new THREE.SphereGeometry(0.008), windowLed.mat), -0.014, 0.014, -0.005),
    at(windowLed.glow, -0.014, 0.014, -0.005),
    at(new THREE.Mesh(new THREE.SphereGeometry(0.008), doorLed.mat), -0.014, 0.014, -0.025),
    at(doorLed.glow, -0.014, 0.014, -0.025),
    at(new THREE.Mesh(new THREE.SphereGeometry(0.009), adviceLedMat), -0.014, 0.014, 0.03),
    at(adviceGlow, -0.014, 0.014, 0.03),
    box(0.055, 0.012, 0.13, COLORS.pcb, { roughness: 0.5 }),
    at(new THREE.Mesh(new THREE.SphereGeometry(0.008), ledMat(0x3fa9ff)), 0.012, 0.012, -0.04),
    at(box(0.025, 0.006, 0.025, 0x6a2fa0), 0, 0.01, 0.1),
    nodeHalo,
  ], [deskTopX - 0.25, 0.77, d.z + 0.12]);
  glowMats.climate = nodeHalo.material;

  const scdHalo = halo(0.1);
  sensorGroup('co2', [
    box(0.035, 0.012, 0.035, COLORS.sensorBody, { roughness: 0.4 }),
    at(new THREE.Mesh(new THREE.SphereGeometry(0.006), ledMat(0x48d17a)), 0.01, 0.01, 0.01),
    scdHalo,
  ], [deskTopX + 0.22, 0.77, d.z + 0.17]);
  glowMats.co2 = scdHalo.material;

  // Wall probe: steel tip taped flat to the balcony wall, a breathing ring as its hotspot glow, and around it a
  // soft patch coloured by the humidity at the wall surface (green < 70 %, amber < 80 %, red above; pulses red)
  const PW = ROOM.probes.wall;
  const steel = new THREE.MeshStandardMaterial({ color: 0xc9ccd1, metalness: 0.9, roughness: 0.25 });
  const tip = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.05, 12), steel);
  tip.rotation.z = Math.PI / 2;
  const ringMat = new THREE.MeshBasicMaterial({ color: COLORS.accent, transparent: true, opacity: 0.5,
    side: THREE.DoubleSide, depthWrite: false });
  const patchMat = new THREE.MeshBasicMaterial({ map: radialTexture(), color: 0x2fb35a, transparent: true, opacity: 0,
    depthWrite: false });
  const patch = at(new THREE.Mesh(new THREE.CircleGeometry(0.45, 40), patchMat), 0, 0, -0.004);
  patch.renderOrder = 1;
  const wallRing = new THREE.Mesh(new THREE.RingGeometry(0.075, 0.09, 48), ringMat);
  wallRing.renderOrder = 3;
  // Mould stain: darkens with the hours the wall spent above 80 % humidity in the shown range (setStain)
  const stainMat = new THREE.MeshBasicMaterial({ map: mouldTexture(), transparent: true, opacity: 0, depthWrite: false });
  const stain = at(new THREE.Mesh(new THREE.CircleGeometry(0.32, 40), stainMat), 0, 0, -0.002);
  stain.renderOrder = 2;
  let stainLevel = 0;
  let stainShown = 0;
  sensorGroup('wall', [
    patch,
    stain,
    wallRing,
    at(tip, 0, 0, 0.006),
    at(box(0.018, 0.022, 0.002, 0xf2f2ee, { roughness: 0.9 }), 0.012, 0, 0.007),   // tape over the sleeve
    new THREE.Mesh(new THREE.CircleGeometry(0.3, 24), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })),
  ], [PW.x, PW.y, back + 0.006]);
  glowMats.wall = ringMat;
  let wallRh = null;
  const nodePos = [deskTopX - 0.25, 0.775, d.z + 0.1];
  cable([[PW.x + 0.03, PW.y, back + 0.01], [PW.x + 0.15, PW.y - 0.2, back + 0.012], [d.x - dw / 2 + 0.05, 0.85, back + 0.015],
    [d.x - dw / 2 + 0.12, 0.78, back + 0.08], nodePos], 0x1a1a1a);

  // Outdoor probe in a radiation shield (stacked white saucers) on the balcony; its cable comes in through the vent
  const PO = ROOM.probes.outdoor;
  const shield = new THREE.Group();
  const shieldMat = new THREE.MeshStandardMaterial({ color: 0xf4f4f0, roughness: 0.5 });
  for (let i = 0; i < 5; i++) {
    const saucer = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.095, 0.02, 28), shieldMat);
    saucer.castShadow = true;
    shield.add(at(saucer, 0, -i * 0.032, 0));
  }
  shield.add(at(new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.005, 0.17, 8), steel), 0, -0.06, 0));
  shield.add(at(box(0.02, 0.02, PO.out, 0x8d9096, { metalness: 0.5, roughness: 0.4 }), 0, 0.02, PO.out / 2));   // arm to the wall
  outdoorGroup.add(at(shield, PO.x, PO.y, back - T - PO.out));
  const shieldTop = [PO.x, PO.y + 0.015, back - T - PO.out];
  // In along the hinge side of the right-hand side window (the frame gap), then down to the desk
  cable([shieldTop, [PO.x, PO.y + 0.25, back - T - 0.1], [screenR + 0.03, 1.35, back - T - 0.02],
    [screenR - 0.01, 1.35, back + 0.02]], 0x1a1a1a);
  cable([[screenR - 0.01, 1.35, back + 0.02], [screenR + 0.15, 1.1, back + 0.03], [d.x - dw / 2 + 0.05, 0.85, back + 0.04],
    [d.x - dw / 2 + 0.12, 0.78, back + 0.1], nodePos], 0x1a1a1a);

  // Cut-away walls: the front wall and the couch's wall as low walls, the doorway a gap in the front one. The door
  // leaf (cut at the same height) fills the gap when closed and swings against the couch's wall when open; the swing
  // area glows yellow like the real door LED while it is open.
  const DR = ROOM.door;
  const CUT = ROOM.cutWallHeight;
  const front = W / 2;
  const doorX0 = DR.x - DR.width / 2;
  const doorX1 = DR.x + DR.width / 2;
  for (const [x0, x1] of [[-L / 2 - T, doorX0], [doorX1, L / 2 + T]]) {
    const seg = at(box(x1 - x0, CUT, T, COLORS.wall, { roughness: 0.95 }), (x0 + x1) / 2, CUT / 2, front + T / 2);
    scene.add(seg);
    lidarTargets.push(seg);
  }
  const leftCut = at(box(T, CUT, W + 2 * T, COLORS.wall, { roughness: 0.95 }), -L / 2 - T / 2, CUT / 2, 0);
  scene.add(leftCut);
  lidarTargets.push(leftCut);

  const hingeSign = DR.hinge === 'right' ? 1 : -1;
  const doorHingeX = DR.x + hingeSign * DR.width / 2;
  const doorPivot = at(new THREE.Group(), doorHingeX, 0, front + T / 2);
  doorPivot.add(at(box(DR.width - 0.01, CUT - 0.005, 0.04, 0x9c6b3f, { roughness: 0.6 }), -hingeSign * DR.width / 2, CUT / 2, 0));
  doorPivot.add(at(box(0.08, 0.02, 0.06, 0xc9a227, { metalness: 0.7, roughness: 0.3 }), -hingeSign * (DR.width - 0.08), CUT - 0.06, 0));   // handle
  doorPivot.userData.interact = 'door';
  scene.add(doorPivot);
  interactables.push(doorPivot, outdoorGroup);
  const swingMat = new THREE.MeshBasicMaterial({ color: 0xffc21a, transparent: true, opacity: 0, depthWrite: false,
    side: THREE.DoubleSide });
  const swing = new THREE.Mesh(new THREE.CircleGeometry(DR.width, 32, hingeSign > 0 ? Math.PI / 2 : 0, Math.PI / 2), swingMat);
  swing.rotation.x = -Math.PI / 2;
  swing.raycast = () => {};
  scene.add(at(swing, doorHingeX, 0.006, front));
  const arcPts = new THREE.EllipseCurve(0, 0, DR.width, DR.width, hingeSign > 0 ? Math.PI / 2 : 0, hingeSign > 0 ? Math.PI : Math.PI / 2)
    .getPoints(24).map((q) => new THREE.Vector3(q.x, 0, -q.y));
  const arcMat = new THREE.LineDashedMaterial({ color: 0x8a7f70, dashSize: 0.05, gapSize: 0.04, transparent: true, opacity: 0 });
  const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(arcPts), arcMat);
  arc.computeLineDistances();
  arc.raycast = () => {};
  scene.add(at(arc, doorHingeX, 0.008, front));
  const DOOR_OPEN_ANGLE = -hingeSign * Math.PI / 2 * 0.95;   // leaf turns into the room

  // Radiators against the front wall; during the heating schedule they warm up and warm air shimmers above them
  const radMat = new THREE.MeshStandardMaterial({ color: 0xf3f2ee, roughness: 0.5, emissive: 0xff7a2a, emissiveIntensity: 0 });
  const radiators = ROOM.heating.radiators.map((r) => {
    const g = new THREE.Group();
    g.add(at(new THREE.Mesh(new THREE.BoxGeometry(r.width, r.height, 0.05), radMat), 0, 0, 0));
    for (let fx = -r.width / 2 + 0.04; fx < r.width / 2 - 0.02; fx += 0.06) {
      g.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.02, r.height - 0.04, 0.012), radMat), fx, 0, -0.031));
    }
    g.traverse((o) => { o.castShadow = o.receiveShadow = true; });
    scene.add(at(g, r.x, 0.12 + r.height / 2, front - 0.045));
    g.userData.interact = 'radiator';
    lidarTargets.push(g);
    interactables.push(g);
    return { ...r, top: 0.12 + r.height };
  });
  const HEAT = 110;
  const HEAT_LIFE = 3;
  const heatPos = new Float32Array(HEAT * 3);
  const heatAge = new Float32Array(HEAT);
  const respawnHeat = (i, randomAge) => {
    const r = radiators[i % radiators.length];
    heatPos.set([r.x + (Math.random() - 0.5) * r.width, r.top, front - 0.08 - Math.random() * 0.05], i * 3);
    heatAge[i] = randomAge ? Math.random() * HEAT_LIFE : 0;
  };
  if (radiators.length) for (let i = 0; i < HEAT; i++) respawnHeat(i, true);
  const heatGeo = new THREE.BufferGeometry();
  heatGeo.setAttribute('position', new THREE.BufferAttribute(heatPos, 3));
  const heatMat = new THREE.PointsMaterial({ color: 0xffb27a, size: 0.03, transparent: true, opacity: 0, depthWrite: false });
  const heat = new THREE.Points(heatGeo, heatMat);
  heat.visible = false;
  heat.frustumCulled = false;
  heat.raycast = () => {};
  scene.add(heat);
  let heatAmt = 0;
  const heatingAt = (ms) => {
    const d = new Date(ms);
    const h = d.getHours() + d.getMinutes() / 60;
    return ROOM.heating.schedule.some(([a, b]) => h >= a && h < b);
  };

  // Cool air pouring in through an open window: pale particles that sink as they spread into the room
  const FLOW = 240;
  const FLOW_LIFE = 4.5;   // s
  const flowPos = new Float32Array(FLOW * 3);
  const flowVel = new Float32Array(FLOW * 3);
  const flowAge = new Float32Array(FLOW);
  const respawnFlow = (i, randomAge) => {
    const [x0, x1, y0, y1] = sashes[i % sashes.length].userData.span;
    flowPos.set([x0 + Math.random() * (x1 - x0), y0 + Math.random() * (y1 - y0), back + 0.05], i * 3);
    flowVel.set([(Math.random() - 0.5) * 0.15, -0.04 - Math.random() * 0.06, 0.3 + Math.random() * 0.25], i * 3);
    flowAge[i] = randomAge ? Math.random() * FLOW_LIFE : 0;
  };
  if (sashes.length) for (let i = 0; i < FLOW; i++) respawnFlow(i, true);
  const flowGeo = new THREE.BufferGeometry();
  flowGeo.setAttribute('position', new THREE.BufferAttribute(flowPos, 3));
  const flowMat = new THREE.PointsMaterial({ color: 0xbfe3ff, size: 0.04, transparent: true, opacity: 0, depthWrite: false });
  const flow = new THREE.Points(flowGeo, flowMat);
  flow.visible = false;
  flow.frustumCulled = false;
  flow.raycast = () => {};
  scene.add(flow);

  let windowOpen = false;
  let doorOpen = true;
  let statesKnown = false;
  // Play: clicks override the data until the next reading (door, window) or fade back on their own
  const nowS = () => performance.now() / 1000;
  let fogBoost = 0, fogClickAt = -1e9;
  let heatBoostUntil = -1e9;
  let co2Boost = 0, co2ClickAt = -1e9;
  let lastCo2 = 420, lastRh = 50;
  function interact(kind) {
    if (kind === 'door') { doorOpen = !doorOpen; statesKnown = true; }
    else if (kind === 'window') { windowOpen = !windowOpen; statesKnown = true; }
    else if (kind === 'glass') { fogBoost = Math.min(1, fogBoost + 0.25); fogClickAt = nowS(); }
    else if (kind === 'radiator') heatBoostUntil = nowS() + 12;
    else if (kind === 'couch') { co2Boost = Math.min(1600, co2Boost + 300); co2ClickAt = nowS(); }
    else if (kind === 'computer') onComputer?.('start');
  }
  let sashOpen = 0;       // 0 closed … 1 open, eased
  let doorOpenAmt = 1;

  // ----- easter egg: the 2-wheel LiDAR robot circling the media table -----
  const R = ROOM.robot;
  const robot = new THREE.Group();
  robot.userData.hotspot = 'robot';
  const darkMat = new THREE.MeshStandardMaterial({ color: 0x24262b, roughness: 0.5 });
  robot.add(at(new THREE.Mesh(new THREE.CylinderGeometry(R.radius, R.radius, 0.05, 32), darkMat), 0, 0.065, 0));
  robot.add(at(new THREE.Mesh(new THREE.CylinderGeometry(R.radius * 0.95, R.radius * 0.95, 0.006, 32),
    new THREE.MeshStandardMaterial({ color: 0x3a3d44, roughness: 0.4 })), 0, 0.112, 0));          // top plate
  for (let k = 0; k < 4; k++) {
    const a = (k / 4) * Math.PI * 2 + Math.PI / 4;
    robot.add(at(new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.022), new THREE.MeshStandardMaterial({ color: 0xc9a227, metalness: 0.7 })),
      Math.cos(a) * 0.07, 0.1, Math.sin(a) * 0.07));                                               // brass standoffs
  }
  const accentMat = new THREE.MeshStandardMaterial({ color: 0x22d3ee, emissive: 0x22d3ee, emissiveIntensity: 1.6 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(R.radius + 0.002, 0.004, 8, 48), accentMat);
  ring.rotation.x = Math.PI / 2;
  robot.add(at(ring, 0, 0.065, 0));
  robot.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.012, 0.006), accentMat), 0, 0.07, R.radius + 0.003));   // "eyes" at the front
  const wheelPivots = [];
  for (const sx of [-1, 1]) {
    const pivot = at(new THREE.Group(), sx * (R.radius + 0.012), 0.035, 0);
    const tyre = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.02, 24), new THREE.MeshStandardMaterial({ color: 0x111214, roughness: 0.9 }));
    tyre.rotation.z = Math.PI / 2;
    pivot.add(tyre);
    pivot.add(at(box(0.022, 0.05, 0.008, 0x8a8f98), 0, 0, 0));   // hub spoke, shows the wheel turning
    robot.add(pivot);
    wheelPivots.push(pivot);
  }
  for (const cz of [-1, 1]) robot.add(at(new THREE.Mesh(new THREE.SphereGeometry(0.012), darkMat), 0, 0.012, cz * 0.07));   // casters
  robot.add(at(new THREE.Mesh(new THREE.CylinderGeometry(0.034, 0.036, 0.02, 24), darkMat), 0, 0.125, 0));                // LiDAR base
  const lidarHead = at(new THREE.Group(), 0, 0.145, 0);
  lidarHead.add(new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.022, 24), new THREE.MeshStandardMaterial({ color: 0x0f1012, roughness: 0.3 })));
  lidarHead.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.01, 0.004),
    new THREE.MeshStandardMaterial({ color: 0xff3b30, emissive: 0xff3b30, emissiveIntensity: 2 })), 0, 0, 0.031));
  robot.add(lidarHead);
  robot.traverse((o) => { o.castShadow = true; });
  scene.add(robot);
  hotspotMeshes.push(robot);

  const robotTagEl = document.createElement('div');
  robotTagEl.className = 'tag robot-tag';
  robotTagEl.innerHTML = '<span class="tag-title">Easter egg</span><span class="tag-value">2-wheel LiDAR robot · in the making</span>';
  robotTagEl.hidden = true;
  robot.add(at(new CSS2DObject(robotTagEl), 0, 0.4, 0));
  let robotTagTimer = null;
  function showRobotTag() {
    robotTagEl.hidden = false;
    clearTimeout(robotTagTimer);
    robotTagTimer = setTimeout(() => { robotTagEl.hidden = true; }, 6000);
  }

  // LiDAR: rays from the spinning head; hits leave a red point cloud that fades out (additive blending)
  const SCAN_POINTS = 1800;
  const scanPos = new Float32Array(SCAN_POINTS * 3);
  const scanCol = new Float32Array(SCAN_POINTS * 3);
  const scanGeo = new THREE.BufferGeometry();
  scanGeo.setAttribute('position', new THREE.BufferAttribute(scanPos, 3));
  scanGeo.setAttribute('color', new THREE.BufferAttribute(scanCol, 3));
  const scan = new THREE.Points(scanGeo, new THREE.PointsMaterial({ size: 0.028, vertexColors: true, transparent: true,
    depthWrite: false, blending: THREE.AdditiveBlending }));
  scan.frustumCulled = false;
  scan.raycast = () => {};
  scene.add(scan);
  const beamGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
  const beam = new THREE.Line(beamGeo, new THREE.LineBasicMaterial({ color: 0xff3b30, transparent: true, opacity: 0.35,
    depthWrite: false, blending: THREE.AdditiveBlending }));
  beam.frustumCulled = false;
  beam.raycast = () => {};
  scene.add(beam);
  const lidarRay = new THREE.Raycaster();
  lidarRay.far = 8;   // the room's walls and invisible bounds stop every ray long before this
  const lidarOrigin = new THREE.Vector3();
  const lidarDir = new THREE.Vector3();
  let scanHead = 0;
  let robotAngle = 0;
  let lidarAngle = 0;

  // ----- room air: tints with CO2, motes thicken with humidity -----
  const airMat = new THREE.MeshBasicMaterial({ color: COLORS.air, transparent: true, opacity: 0, depthWrite: false });
  const air = at(new THREE.Mesh(new THREE.BoxGeometry(L - 0.04, H - 0.04, W - 0.04), airMat), 0, H / 2, 0);
  air.raycast = () => {};
  scene.add(air);

  const MOTES = 420;
  const motePos = new Float32Array(MOTES * 3);
  for (let i = 0; i < MOTES; i++) {
    motePos[i * 3] = (Math.random() - 0.5) * (L - 0.3);
    motePos[i * 3 + 1] = Math.random() * (H - 0.2) + 0.1;
    motePos[i * 3 + 2] = (Math.random() - 0.5) * (W - 0.3);
  }
  const moteGeo = new THREE.BufferGeometry();
  moteGeo.setAttribute('position', new THREE.BufferAttribute(motePos, 3));
  const moteMat = new THREE.PointsMaterial({ color: COLORS.mote, size: 0.03, transparent: true, opacity: 0, depthWrite: false });
  const motes = new THREE.Points(moteGeo, moteMat);
  motes.raycast = () => {};
  scene.add(motes);

  // ----- balcony: slab and railing -----
  const balconyDepth = 1.5;
  scene.add(at(box(L + 0.6, 0.12, balconyDepth, 0xbdb6ab, { roughness: 1 }), 0, -0.08, back - T - balconyDepth / 2));
  const railMat = new THREE.MeshStandardMaterial({ color: 0x3b3f45, metalness: 0.6, roughness: 0.4 });
  const railZ = back - T - balconyDepth + 0.05;
  scene.add(at(new THREE.Mesh(new THREE.BoxGeometry(L + 0.6, 0.04, 0.04), railMat), 0, 1.0, railZ));
  for (let x = -L / 2 - 0.3; x <= L / 2 + 0.31; x += 0.25) {
    scene.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.02, 1.0, 0.02), railMat), x, 0.5, railZ));
  }

  // ----- rain / snow behind the balcony wall -----
  const DROPS = 1200;
  const dropPos = new Float32Array(DROPS * 3);
  const resetDrop = (i, anyHeight) => {
    dropPos[i * 3] = (Math.random() - 0.5) * 14;
    dropPos[i * 3 + 1] = anyHeight ? Math.random() * 5 + GROUND : 4.5;
    dropPos[i * 3 + 2] = back - T - 0.2 - Math.random() * 9;
  };
  for (let i = 0; i < DROPS; i++) resetDrop(i, true);
  const dropGeo = new THREE.BufferGeometry();
  dropGeo.setAttribute('position', new THREE.BufferAttribute(dropPos, 3));
  const dropMat = new THREE.PointsMaterial({ color: 0xa9c4dd, size: 0.035, transparent: true, opacity: 0.85, depthWrite: false });
  const drops = new THREE.Points(dropGeo, dropMat);
  drops.visible = false;
  drops.raycast = () => {};
  scene.add(drops);
  let precipType = null;

  // ---------- floating tags ----------

  const tags = {};
  for (const [id, hs] of Object.entries(ROOM.hotspots)) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'tag';
    el.dataset.hotspot = id;
    el.innerHTML = `<span class="tag-title">${hs.title}</span><span class="tag-value">…</span>`;
    el.addEventListener('click', (e) => { e.stopPropagation(); onSelect?.(id); });
    scene.add(at(new CSS2DObject(el), ...hs.anchor));
    tags[id] = el;
  }

  // ---------- computer: the room's replay on the desk monitor ----------

  const replayTarget = new THREE.WebGLRenderTarget(768, 432);
  replayTarget.texture.colorSpace = THREE.SRGBColorSpace;
  const roomCam = new THREE.PerspectiveCamera(36, 768 / 432, 0.1, 160);
  let computerMode = false;
  const clockEl = document.createElement('div');
  clockEl.className = 'tag computer-clock';
  clockEl.hidden = true;
  clockEl.innerHTML = '<span class="tag-title">Replay · last 24 h</span><span class="tag-value">…</span>' +
    '<span class="computer-progress"><i></i></span><span class="tag-title">click anywhere or Esc to stop</span>';
  monitorScreen.add(at(new CSS2DObject(clockEl), 0, 0.27, 0));

  // ---------- camera motion ----------

  let tween = null;
  function flyTo(position, target, ms = 1400) {
    tween = { p0: camera.position.clone(), t0: controls.target.clone(), p1: v3(position), t1: v3(target),
      start: performance.now(), ms };
    controls.enabled = false;
  }

  function defaultView() {
    // Step back on narrow (portrait) screens so the whole room fits
    const aspect = container.clientWidth / Math.max(1, container.clientHeight);
    const t = v3(DEFAULT_VIEW.target);
    const offset = v3(DEFAULT_VIEW.position).sub(t).multiplyScalar(aspect < 1 ? 1 / aspect ** 0.75 : 1);
    return { position: t.clone().add(offset).toArray(), target: t.toArray() };
  }

  // Intro: start far above and swoop in
  const start = defaultView();
  const startTarget = v3(start.target);
  camera.position.copy(v3(start.position).sub(startTarget).multiplyScalar(2.6).add(startTarget).add(v3([0, 6, 0])));
  controls.target.copy(startTarget);
  camera.lookAt(startTarget);
  flyTo(start.position, start.target, 2800);

  // ---------- picking ----------

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let hovered = null;
  let selected = null;
  let downAt = null;

  /** Nearest clickable thing under the pointer: { interact } (play) or { hotspot } (opens a panel), or null. */
  function pick(event) {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((event.clientX - r.left) / r.width) * 2 - 1, -((event.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    for (const hit of raycaster.intersectObjects([...interactables, ...hotspotMeshes], true)) {
      let o = hit.object;
      let inSash = false;
      for (let a = o; a; a = a.parent) if (a.userData.interact === 'window') inSash = true;
      if (o.material === glassMat && !inSash) return { interact: 'glass' };
      for (; o; o = o.parent) {
        if (o.userData.interact) return { interact: o.userData.interact };
        if (o.userData.hotspot) return { hotspot: o.userData.hotspot };
      }
    }
    return null;
  }

  renderer.domElement.addEventListener('pointermove', (e) => {
    const hit = computerMode ? null : pick(e);
    hovered = hit?.hotspot ?? null;
    renderer.domElement.style.cursor = hit ? 'pointer' : '';
    for (const [id, el] of Object.entries(tags)) el.classList.toggle('is-hover', id === hovered);
  });
  renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
    if (computerMode) { onComputer?.('stop'); return; }
    const hit = pick(e);
    if (!hit) return;
    if (hit.interact) interact(hit.interact);
    else if (hit.hotspot === 'robot') showRobotTag();
    else onSelect?.(hit.hotspot);
  });

  // ---------- resize + loop ----------

  function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    renderer.setSize(w, h);
    labelRenderer.setSize(w, h);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const clock = new THREE.Clock();
  renderer.setAnimationLoop(() => {
    const dt = Math.min(clock.getDelta(), 0.1);
    const time = clock.elapsedTime;

    if (tween) {
      const k = Math.min(1, (performance.now() - tween.start) / tween.ms);
      const e = easeInOut(k);
      camera.position.lerpVectors(tween.p0, tween.p1, e);
      controls.target.lerpVectors(tween.t0, tween.t1, e);
      camera.lookAt(controls.target);
      if (k === 1) { tween = null; controls.enabled = !computerMode; }
    } else {
      controls.update();   // only outside fly-overs, so its limits never fight the animation
    }

    // Room air: CO2 tints it (plus people "added" by clicking the couch), humidity thickens the motes
    if (nowS() - co2ClickAt > 2) co2Boost = Math.max(0, co2Boost - dt * 80);
    airMat.opacity = Math.min(0.16, Math.max(0, (lastCo2 + co2Boost - 500) / 1500) * 0.16);
    moteMat.opacity = Math.min(0.9, Math.max(0.05, (lastRh - 35) / 45));

    // Sensor halos breathe; the selected or hovered one glows brighter
    for (const [id, mat] of Object.entries(glowMats)) {
      const base = id === 'wall' ? 0.35 : 0.1;
      const boost = id === selected ? 0.35 : id === hovered ? 0.25 : 0;
      mat.opacity = base + boost + 0.08 * Math.sin(time * 2.4 + id.length);
    }
    tv.update(dt);
    adviceLedMat.emissiveIntensity = adviceOn ? 2.5 + 1.5 * Math.sin(time * 4) : 0;
    adviceGlow.material.opacity = adviceOn ? 0.35 + 0.2 * Math.sin(time * 4) : 0;

    // Sun follows the clock (or the replay time); at night the weather's moonlight stays overhead
    const now = sceneTime ?? Date.now();
    const sp = sunPosition(now, location.lat, location.lon);
    if (sp.elevation > -1) {
      const [sx, sy, sz] = sunDirection(sp, ROOM.balconyFacingDeg);
      sun.position.set(sun.target.position.x + sx * 14, Math.max(0.4, sy * 14), sun.target.position.z + sz * 14);
      sun.intensity = baseSun * Math.min(1, (sp.elevation + 1) / 10);
    } else {
      sun.position.set(-1.5, 7, back - 9);
      sun.intensity = baseSun;
    }

    // Glass mists up near the dew point; the wall stain follows the hours of high humidity
    if (nowS() - fogClickAt > 1.2) fogBoost = Math.max(0, fogBoost - dt * 0.2);
    fogShown += (Math.max(fog, fogBoost) - fogShown) * Math.min(1, dt * 3);
    glassMat.opacity = 0.22 + 0.5 * fogShown;
    glassMat.color.copy(GLASS_CLEAR).lerp(GLASS_FOGGED, fogShown);
    glassMat.roughness = 0.05 + 0.6 * fogShown;
    stainShown += (stainLevel - stainShown) * Math.min(1, dt * 1.5);
    stainMat.opacity = 0.75 * stainShown;

    // Heating schedule: radiators glow faintly, warm air rises
    heatAmt += ((heatingAt(now) || nowS() < heatBoostUntil ? 1 : 0) - heatAmt) * Math.min(1, dt * 0.8);
    radMat.emissiveIntensity = 0.35 * heatAmt;
    heat.visible = radiators.length > 0 && heatAmt > 0.02;
    if (heat.visible) {
      heatMat.opacity = 0.35 * heatAmt;
      for (let i = 0; i < HEAT; i++) {
        heatAge[i] += dt;
        heatPos[i * 3 + 1] += dt * (0.22 + 0.1 * Math.sin(i));
        heatPos[i * 3] += Math.sin(time * 3 + i) * dt * 0.03;
        heatPos[i * 3 + 2] -= dt * 0.04;
        if (heatAge[i] > HEAT_LIFE) respawnHeat(i, false);
      }
      heatGeo.attributes.position.needsUpdate = true;
    }

    // Window sashes and the door ease towards the button states; LEDs mirror the real ones
    const ease = Math.min(1, dt * 2.5);
    sashOpen += ((windowOpen ? 1 : 0) - sashOpen) * ease;
    for (const s of sashes) s.rotation.y = s.userData.swing * 1.1 * sashOpen;
    doorOpenAmt += ((doorOpen ? 1 : 0) - doorOpenAmt) * ease;
    doorPivot.rotation.y = DOOR_OPEN_ANGLE * doorOpenAmt;
    swingMat.opacity = 0.2 * doorOpenAmt;
    arcMat.opacity = 0.9 * doorOpenAmt;
    for (const [led, on] of [[windowLed, statesKnown && windowOpen], [doorLed, statesKnown && doorOpen]]) {
      led.mat.emissiveIntensity = on ? 2.4 : 0;
      led.glow.material.opacity = on ? 0.3 : 0;
    }
    if (wallRh == null) {
      patchMat.opacity = 0;
    } else {
      patchMat.color.setHex(wallRh >= 80 ? 0xe5484d : wallRh >= 70 ? 0xf5a524 : 0x2fb35a);
      patchMat.opacity = wallRh >= 80 ? 0.42 + 0.14 * Math.sin(time * 3) : 0.32;
    }

    // Incoming air while a window is open
    flow.visible = sashes.length > 0 && sashOpen > 0.02;
    if (flow.visible) {
      flowMat.opacity = 0.55 * sashOpen;
      for (let i = 0; i < FLOW; i++) {
        flowAge[i] += dt;
        flowVel[i * 3 + 1] -= 0.03 * dt;   // cold air sinks
        for (let a = 0; a < 3; a++) flowPos[i * 3 + a] += flowVel[i * 3 + a] * dt;
        if (flowAge[i] > FLOW_LIFE || flowPos[i * 3 + 1] < 0.03) respawnFlow(i, false);
      }
      flowGeo.attributes.position.needsUpdate = true;
    }

    // Robot: drive the ellipse, wheels turning, LiDAR spinning
    robotAngle += (R.speed / ((R.radiusX + R.radiusZ) / 2)) * dt;
    const rxp = R.center[0] + R.radiusX * Math.cos(robotAngle);
    const rzp = R.center[1] + R.radiusZ * Math.sin(robotAngle);
    robot.position.set(rxp, 0, rzp);
    robot.rotation.y = Math.atan2(-R.radiusX * Math.sin(robotAngle), R.radiusZ * Math.cos(robotAngle));
    for (const w of wheelPivots) w.rotation.x += (R.speed / 0.035) * dt;
    const a0 = lidarAngle;
    lidarAngle += dt * Math.PI * 2 * 1.2;   // 1.2 turns per second: readable, not frantic
    lidarHead.rotation.y = lidarAngle;
    lidarOrigin.set(rxp, 0.145, rzp);
    const RAYS = 5;
    for (let k = 1; k <= RAYS; k++) {
      const a = robot.rotation.y + a0 + ((lidarAngle - a0) * k) / RAYS;
      lidarDir.set(Math.sin(a), 0, Math.cos(a));
      lidarRay.set(lidarOrigin, lidarDir);
      const hit = lidarRay.intersectObjects(lidarTargets, true)[0];
      const end = hit ? hit.point : lidarOrigin.clone().addScaledVector(lidarDir, lidarRay.far);
      if (hit) {
        scanPos.set([hit.point.x, hit.point.y, hit.point.z], scanHead * 3);
        scanCol.set([1, 0.22, 0.16], scanHead * 3);
        scanHead = (scanHead + 1) % SCAN_POINTS;
      }
      if (k === RAYS) beamGeo.attributes.position.setXYZ(1, end.x, end.y, end.z);
    }
    beamGeo.attributes.position.setXYZ(0, lidarOrigin.x, lidarOrigin.y, lidarOrigin.z);
    beamGeo.attributes.position.needsUpdate = true;
    for (let i = 0; i < scanCol.length; i++) scanCol[i] *= 0.993;   // points fade over ~5 s
    scanGeo.attributes.position.needsUpdate = true;
    scanGeo.attributes.color.needsUpdate = true;

    // Motes drift upward slowly and wrap
    const mp = moteGeo.attributes.position.array;
    for (let i = 0; i < MOTES; i++) {
      mp[i * 3 + 1] += dt * 0.05;
      mp[i * 3] += Math.sin(time * 0.3 + i) * dt * 0.02;
      if (mp[i * 3 + 1] > H - 0.1) mp[i * 3 + 1] = 0.1;
    }
    moteGeo.attributes.position.needsUpdate = true;

    if (drops.visible) {
      const speed = precipType === 'snow' ? 0.8 : 7;
      for (let i = 0; i < DROPS; i++) {
        dropPos[i * 3 + 1] -= dt * speed;
        if (precipType === 'snow') dropPos[i * 3] += Math.sin(time + i) * dt * 0.2;
        if (dropPos[i * 3 + 1] < GROUND) resetDrop(i, false);
      }
      dropGeo.attributes.position.needsUpdate = true;
    }

    // Computer mode: render the room from the overview camera onto the monitor (the screen hidden to avoid feedback)
    if (computerMode) {
      monitorScreen.visible = false;
      renderer.setRenderTarget(replayTarget);
      renderer.render(scene, roomCam);
      renderer.setRenderTarget(null);
      monitorScreen.visible = true;
    }
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
  });

  // ---------- public API ----------

  return {
    /** Weather row from weather_hourly (or null). */
    setWeather(w) {
      if (!w) return;
      const look = skyFor(w.weather_code ?? 3, w.is_day ?? true);
      paintSky(skyCanvas, look.top, look.bottom);
      skyTex.needsUpdate = true;
      scene.fog.color.set(look.bottom);
      scene.fog.near = look.fog ? 6 : 22;
      scene.fog.far = look.fog ? 30 : 70;
      baseSun = look.sun;
      sun.color.setHex(look.sunColor);
      hemi.intensity = w.is_day ? 1.6 : 0.7;
      lamp.intensity = w.is_day ? 4 : 14;
      precipType = look.precip;
      drops.visible = Boolean(look.precip);
      dropMat.size = look.precip === 'snow' ? 0.06 : 0.035;
      dropMat.color.setHex(look.precip === 'snow' ? 0xffffff : 0xa9c4dd);
    },

    /** Latest indoor reading: CO2 tints the air, humidity thickens the motes. */
    setIndoor(r) {
      if (!r) return;
      lastCo2 = r.co2_ppm ?? 420;
      if (r.rh != null) lastRh = r.rh;
    },

    /** Zoom into the desk monitor, which then shows the room from the overview camera (replay). */
    enterComputer() {
      computerMode = true;
      const v = defaultView();
      roomCam.position.copy(v3(v.position));
      roomCam.lookAt(v3(v.target));
      screenMat.map = replayTarget.texture;
      screenMat.needsUpdate = true;
      clockEl.hidden = false;
      const p = monitorScreen.getWorldPosition(new THREE.Vector3());
      flyTo([p.x, p.y + 0.06, p.z + 0.72], p.toArray(), 1400);
    },

    /** Back from the monitor to the view before (or the selected sensor's view). */
    exitComputer() {
      if (!computerMode) return;
      computerMode = false;
      screenMat.map = idleScreen;
      screenMat.needsUpdate = true;
      clockEl.hidden = true;
      const v = selected ? ROOM.hotspots[selected].view : defaultView();
      flyTo(v.position, v.target, 1600);
    },

    /** Clock text and progress 0..1 shown above the monitor during the replay. */
    setComputerClock(text, progress) {
      clockEl.querySelector('.tag-value').textContent = text;
      clockEl.querySelector('.computer-progress i').style.width = `${Math.round(Math.min(1, Math.max(0, progress)) * 100)}%`;
    },

    /**
     * Window/door button states from the latest reading: { windowOpen, doorOpen, known }. The side windows swing,
     * the door symbol turns, the red/yellow LEDs on the room node light (only when the states are known).
     */
    setStates({ windowOpen: w, doorOpen: dr, known }) {
      windowOpen = Boolean(w);
      doorOpen = Boolean(dr);
      statesKnown = Boolean(known);
    },

    /** Time the scene shows: null = now (live), or a timestamp during replay. Drives the sun and the heating. */
    setTime(ms) {
      sceneTime = ms ?? null;
    },

    /** How misted the balcony glass is, 0..1 (physics.glassFog). */
    setGlass({ fog: f }) {
      fog = Number.isFinite(f) ? Math.min(1, Math.max(0, f)) : 0;
    },

    /** Mould stain strength 0..1 around the wall probe (hours above 80 % at the wall, scaled). */
    setStain(level) {
      stainLevel = Number.isFinite(level) ? Math.min(1, Math.max(0, level)) : 0;
    },

    /** Humidity at the wall surface (%), or null without a probe reading: colours the patch around the probe. */
    setWall({ surfaceRh }) {
      wallRh = surfaceRh != null && Number.isFinite(surfaceRh) ? surfaceRh : null;
    },

    /** Ventilation advice action ('open' | 'keep' | 'unknown'): the room node's LED lights up on 'open'. */
    setAdvice(action) {
      adviceOn = action === 'open';
    },

    /** { hotspotId: 'value text' } */
    setTagValues(values) {
      for (const [id, text] of Object.entries(values)) {
        const v = tags[id]?.querySelector('.tag-value');
        if (v) v.textContent = text;
      }
    },

    select(id) {
      selected = id;
      for (const [tid, el] of Object.entries(tags)) el.classList.toggle('is-selected', tid === id);
      if (id) flyTo(ROOM.hotspots[id].view.position, ROOM.hotspots[id].view.target);
      else {
        const v = defaultView();
        flyTo(v.position, v.target);
      }
    },
  };
}
