// Three.js view of the backend simulation. Every object is built from telemetry
// geometry (positions, sizes, heights, labels) in simulation coordinates; nothing
// here simulates or predicts motion. Interpolation comes from SceneAnimator.
//
// Coordinate mapping: simulation (x, y) in metres -> three (x, 0, -y), y up.
// A rotation of `theta` about +Y turns the robot's +x axis to (cos, -sin) in x/z,
// which is (cos, sin) in simulation coordinates, so heading maps directly.

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const ROUTE_Y = 0.012;
const REVEAL_MS = 700;
const GHOST_MS = 2600;
const HIGHLIGHT_MS = 2500;
const APPEAR_MS = 500;

const S = (x, y, h = 0) => new THREE.Vector3(x, h, -y);

// ---------------------------------------------------------------- utilities
function seeded(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

function concreteTexture() {
  const size = 512;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.fillStyle = '#b8b4ac';
  g.fillRect(0, 0, size, size);
  const rnd = seeded('floor');
  for (let i = 0; i < 9000; i += 1) {
    const v = 150 + rnd() * 70;
    g.fillStyle = `rgba(${v},${v - 3},${v - 8},${0.05 + rnd() * 0.12})`;
    g.fillRect(rnd() * size, rnd() * size, 1 + rnd() * 2.2, 1 + rnd() * 2.2);
  }
  for (let i = 0; i < 14; i += 1) {
    const cx = rnd() * size;
    const cy = rnd() * size;
    const grad = g.createRadialGradient(cx, cy, 0, cx, cy, 60 + rnd() * 120);
    grad.addColorStop(0, `rgba(90,85,78,${0.04 + rnd() * 0.05})`);
    grad.addColorStop(1, 'rgba(90,85,78,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, size, size);
  }
  // Saw-cut expansion joints at the tile edge (one tile = 5 m slab).
  g.strokeStyle = 'rgba(70,66,60,0.55)';
  g.lineWidth = 2;
  g.strokeRect(1, 1, size - 2, size - 2);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function plankTexture() {
  const c = document.createElement('canvas');
  c.width = 128;
  c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#a77b4a';
  g.fillRect(0, 0, 128, 128);
  const rnd = seeded('plank');
  for (let i = 0; i < 4; i += 1) {
    g.fillStyle = `rgba(${120 + rnd() * 30},${85 + rnd() * 20},${45 + rnd() * 15},1)`;
    g.fillRect(0, i * 32 + 1, 128, 30);
    g.strokeStyle = 'rgba(60,40,20,0.25)';
    for (let k = 0; k < 6; k += 1) {
      g.beginPath();
      g.moveTo(0, i * 32 + 4 + rnd() * 24);
      g.bezierCurveTo(40, i * 32 + rnd() * 30, 90, i * 32 + rnd() * 30, 128, i * 32 + 4 + rnd() * 24);
      g.stroke();
    }
  }
  g.strokeStyle = 'rgba(40,25,10,0.6)';
  g.lineWidth = 2;
  g.strokeRect(1, 1, 126, 126);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function textSprite(text, { color = '#f2f1ee', bg = 'rgba(14,17,19,0.78)', height = 0.28 } = {}) {
  const c = document.createElement('canvas');
  const g = c.getContext('2d');
  const font = '600 44px -apple-system, "Segoe UI", Roboto, Arial, sans-serif';
  g.font = font;
  const w = Math.ceil(g.measureText(text).width) + 36;
  c.width = w;
  c.height = 68;
  g.font = font;
  g.fillStyle = bg;
  g.beginPath();
  g.roundRect(0, 0, w, 68, 10);
  g.fill();
  g.fillStyle = color;
  g.textBaseline = 'middle';
  g.fillText(text, 18, 36);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set((height * w) / 68, height, 1);
  sprite.renderOrder = 10;
  return sprite;
}

function disposeTree(obj) {
  obj.traverse((o) => {
    o.geometry?.dispose();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of mats) {
      m.map?.dispose();
      m.dispose();
    }
  });
}

// Shared materials (created once per scene).
function makeMaterials() {
  const std = (color, roughness = 0.8, metalness = 0) => new THREE.MeshStandardMaterial({ color, roughness, metalness });
  return {
    upright: std('#2c5d8f', 0.55, 0.4),
    beam: std('#d4742a', 0.5, 0.35),
    deck: std('#8f9497', 0.7, 0.3),
    carton: [std('#b8905c', 0.9), std('#a8814f', 0.9), std('#c49d68', 0.9), std('#9e7b4c', 0.9)],
    wrap: new THREE.MeshStandardMaterial({ color: '#dfe3e3', roughness: 0.35, transparent: true, opacity: 0.85 }),
    wood: std('#a57a49', 0.85),
    crate: new THREE.MeshStandardMaterial({ map: plankTexture(), roughness: 0.85 }),
    concrete: std('#9b9993', 0.95),
    safety: std('#e2b31b', 0.6),
    dark: std('#2b2f33', 0.7),
    cone: std('#e8641d', 0.6),
    white: std('#f1f1ef', 0.5),
    vest: std('#c8e03a', 0.6),
    clothes: std('#36414d', 0.85),
    skin: std('#c99a78', 0.8),
    wall: std('#8d8b86', 0.95),
    bumper: std('#2a2c2e', 0.6),
    paint: new THREE.MeshStandardMaterial({ color: '#d9b21d', roughness: 0.7 }),
    chassis: std('#e9e8e4', 0.45, 0.1),
    chassisDark: std('#30353a', 0.5, 0.3),
    rubber: std('#151719', 0.9),
    hub: std('#9aa3aa', 0.4, 0.6),
    lens: new THREE.MeshStandardMaterial({ color: '#0d1b24', roughness: 0.15, metalness: 0.4 }),
    accent: std('#0f6e6a', 0.5, 0.2),
  };
}

// ---------------------------------------------------------------- obstacle models
function box(w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** Warehouse pallet racking sized to the obstacle footprint and height. */
function buildShelf(o, M) {
  const g = new THREE.Group();
  const rnd = seeded(o.id);
  const L = Math.max(o.w, o.h); // long side
  const D = Math.min(o.w, o.h);
  const H = o.height;
  const along = o.w >= o.h; // long side along simulation x
  const post = 0.07;
  const bays = Math.max(1, Math.round(L / 1.25));
  const levels = [0.08, H * 0.36, H * 0.68, H - 0.04];
  const inner = new THREE.Group();
  for (let i = 0; i <= bays; i += 1) {
    const x = -L / 2 + post / 2 + (i * (L - post)) / bays;
    for (const z of [-D / 2 + post / 2, D / 2 - post / 2]) inner.add(box(post, H, post, M.upright, x, H / 2, z));
  }
  levels.forEach((y, i) => {
    for (const z of [-D / 2 + 0.03, D / 2 - 0.03]) inner.add(box(L, 0.07, 0.05, M.beam, 0, y, z));
    // Top level is open (beams only), as on real pallet racking.
    if (i < levels.length - 1) inner.add(box(L - 0.02, 0.025, D - 0.06, M.deck, 0, y + 0.045, 0));
  });
  // Cartons on each deck except the top cap.
  for (let li = 0; li < levels.length - 1; li += 1) {
    const base = levels[li] + 0.06;
    const room = levels[li + 1] - base - 0.08;
    let x = -L / 2 + 0.08;
    while (x < L / 2 - 0.3) {
      const w = 0.28 + rnd() * 0.35;
      if (x + w > L / 2 - 0.06) break;
      if (rnd() > 0.18) {
        const h = Math.min(room, 0.22 + rnd() * room * 0.8);
        const d = D * (0.55 + rnd() * 0.3);
        inner.add(box(w, h, d, M.carton[Math.floor(rnd() * M.carton.length)], x + w / 2, base + h / 2, (rnd() - 0.5) * 0.08));
      }
      x += w + 0.04 + rnd() * 0.08;
    }
  }
  if (!along) inner.rotation.y = Math.PI / 2;
  g.add(inner);
  return g;
}

function buildPallet(o, M) {
  const g = new THREE.Group();
  const w = o.w;
  const d = o.h;
  for (const z of [-d / 2 + 0.05, 0, d / 2 - 0.05]) g.add(box(w, 0.1, 0.1, M.wood, 0, 0.05, z));
  for (let i = 0; i < 6; i += 1) g.add(box(0.12, 0.022, d, M.wood, -w / 2 + 0.06 + (i * (w - 0.12)) / 5, 0.111, 0));
  const loadH = Math.max(o.height - 0.13, 0.1);
  g.add(box(w * 0.94, loadH, d * 0.92, M.wrap, 0, 0.122 + loadH / 2, 0));
  return g;
}

function buildBarrier(o, M) {
  // Precast concrete barrier with a painted safety band (scenario walls and added barriers).
  const g = new THREE.Group();
  const H = o.height;
  g.add(box(o.w, H * 0.92, o.h, M.concrete, 0, (H * 0.92) / 2, 0));
  g.add(box(o.w + 0.02, H * 0.08, o.h + 0.02, M.safety, 0, H * 0.96, 0));
  g.add(box(o.w + 0.03, 0.06, o.h + 0.03, M.dark, 0, 0.03, 0));
  return g;
}

function buildCrate(o, M) {
  const g = new THREE.Group();
  const size = o.shape === 'circle' ? o.r * 2 * 0.85 : null;
  const w = size ?? o.w;
  const d = size ?? o.h;
  const H = o.height;
  g.add(box(w, H, d, M.crate, 0, H / 2, 0));
  for (const y of [0.04, H - 0.04]) g.add(box(w + 0.02, 0.05, d + 0.02, M.wood, 0, y, 0));
  return g;
}

function buildCone(o, M) {
  const g = new THREE.Group();
  const r = o.r;
  const base = new THREE.Mesh(new THREE.BoxGeometry(r * 2, 0.04, r * 2), M.dark);
  base.position.y = 0.02;
  base.castShadow = base.receiveShadow = true;
  const cone = new THREE.Mesh(new THREE.ConeGeometry(r * 0.7, o.height, 24), M.cone);
  cone.position.y = 0.04 + o.height / 2;
  cone.castShadow = true;
  const band = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.36, r * 0.46, o.height * 0.14, 24), M.white);
  band.position.y = 0.04 + o.height * 0.52;
  g.add(base, cone, band);
  return g;
}

function buildPerson(o, M) {
  const g = new THREE.Group();
  const H = o.height;
  const add = (mesh, y) => {
    mesh.position.y = y;
    mesh.castShadow = true;
    g.add(mesh);
    return mesh;
  };
  for (const z of [-0.09, 0.09]) {
    const leg = add(new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.055, H * 0.47, 12), M.clothes), H * 0.235);
    leg.position.z = z;
  }
  add(new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.14, H * 0.32, 16), M.vest), H * 0.63);
  for (const z of [-0.21, 0.21]) {
    const arm = add(new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, H * 0.3, 10), M.clothes), H * 0.62);
    arm.position.z = z;
  }
  add(new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), M.skin), H * 0.87);
  add(new THREE.Mesh(new THREE.SphereGeometry(0.115, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), M.white), H * 0.9);
  return g;
}

function buildObstacle(o, M) {
  const builders = { shelf: buildShelf, pallet: buildPallet, barrier: buildBarrier, cone: buildCone, person: buildPerson };
  const group = (builders[o.label] || buildCrate)(o, M);
  group.userData.obstacleId = o.id;
  group.traverse((c) => (c.userData.obstacleId = o.id));
  return group;
}

// ---------------------------------------------------------------- robot model
/** Differential-drive AMR: two drive wheels on a centre axle, front/rear casters, camera mast at 0.5 m. */
function buildRobot(M, cameraHeight = 0.5, cameraOffset = 0.32) {
  const g = new THREE.Group();
  const R = 0.3; // collision radius from the backend
  const body = new THREE.Group();
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.92, R * 0.95, 0.16, 40), M.chassisDark);
  deck.position.y = 0.13;
  const top = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.86, R * 0.9, 0.05, 40), M.chassis);
  top.position.y = 0.235;
  const bumper = new THREE.Mesh(new THREE.TorusGeometry(R * 0.95, 0.018, 8, 48), M.rubber);
  bumper.rotation.x = Math.PI / 2;
  bumper.position.y = 0.09;
  for (const m of [deck, top, bumper]) {
    m.castShadow = true;
    m.receiveShadow = true;
    body.add(m);
  }
  // Forward-facing accent stripe so the front is obvious.
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.012, 0.3), M.accent);
  stripe.position.set(R * 0.55, 0.262, 0);
  body.add(stripe);
  g.add(body);

  const wheels = [];
  for (const side of [1, -1]) {
    const wheel = new THREE.Group();
    const tyre = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.045, 28), M.rubber);
    tyre.rotation.x = Math.PI / 2;
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.05, 16), M.hub);
    hub.rotation.x = Math.PI / 2;
    // Spoke bar makes rotation visible.
    const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.016, 0.052), M.hub);
    wheel.add(tyre, hub, spoke);
    wheel.position.set(0, 0.075, side * (R * 0.92));
    wheel.traverse((m) => (m.castShadow = true));
    g.add(wheel);
    wheels.push({ wheel, side });
  }
  for (const x of [R * 0.62, -R * 0.62]) {
    const caster = new THREE.Mesh(new THREE.SphereGeometry(0.028, 12, 10), M.hub);
    caster.position.set(x, 0.028, 0);
    g.add(caster);
  }
  // Camera mast and housing at the backend's configured camera height/offset.
  const mastX = Math.min(cameraOffset - 0.06, R * 0.7);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, cameraHeight - 0.26, 10), M.chassisDark);
  mast.position.set(mastX, 0.26 + (cameraHeight - 0.26) / 2, 0);
  const housing = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.06, 0.12), M.chassisDark);
  housing.position.set(mastX + 0.02, cameraHeight, 0);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.02, 16), M.lens);
  lens.rotation.z = Math.PI / 2;
  lens.position.set(mastX + 0.065, cameraHeight, 0);
  for (const m of [mast, housing, lens]) {
    m.castShadow = true;
    g.add(m);
  }
  // Status light ring (colour set from the mission status).
  const ledMat = new THREE.MeshStandardMaterial({ color: '#3fc1b5', emissive: '#3fc1b5', emissiveIntensity: 0.8 });
  const led = new THREE.Mesh(new THREE.TorusGeometry(R * 0.88, 0.008, 6, 48), ledMat);
  led.rotation.x = Math.PI / 2;
  led.position.y = 0.212;
  g.add(led);
  return { group: g, wheels, ledMat };
}

const LED = {
  idle: '#9aa5ab',
  planning: '#3fc1b5',
  navigating: '#3fc1b5',
  replanning: '#f0b429',
  paused: '#f0b429',
  goal_reached: '#5fd38d',
  error: '#ff5d4f',
  blocked: '#ff5d4f',
  stopped: '#9aa5ab',
};

// ---------------------------------------------------------------- overlays
function ribbonGeometry(path, width) {
  // Resample to ~0.08 m so the reveal animation is smooth.
  const pts = [];
  for (let i = 1; i < path.length; i += 1) {
    const [ax, ay] = path[i - 1];
    const [bx, by] = path[i];
    const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / 0.08));
    for (let k = 0; k < n; k += 1) pts.push([ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n]);
  }
  pts.push(path[path.length - 1]);
  const pos = [];
  const idx = [];
  for (let i = 0; i < pts.length; i += 1) {
    const a = pts[Math.max(i - 1, 0)];
    const b = pts[Math.min(i + 1, pts.length - 1)];
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    const L = Math.hypot(dx, dy) || 1;
    dx /= L;
    dy /= L;
    const nx = -dy * (width / 2);
    const ny = dx * (width / 2);
    pos.push(pts[i][0] + nx, ROUTE_Y, -(pts[i][1] + ny), pts[i][0] - nx, ROUTE_Y, -(pts[i][1] - ny));
    if (i > 0) {
      const j = i * 2;
      idx.push(j - 2, j - 1, j, j - 1, j + 1, j);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.userData.segments = pts.length - 1;
  return geo;
}

function outlinePoints(o, pad) {
  const pts = [];
  if (o.shape === 'circle') {
    for (let i = 0; i <= 48; i += 1) {
      const a = (i / 48) * Math.PI * 2;
      pts.push(S(o.x + Math.cos(a) * (o.r + pad), o.y + Math.sin(a) * (o.r + pad), 0.015));
    }
    return pts;
  }
  const hw = o.w / 2;
  const hh = o.h / 2;
  const corners = [
    [hw, hh, 0],
    [-hw, hh, Math.PI / 2],
    [-hw, -hh, Math.PI],
    [hw, -hh, (3 * Math.PI) / 2],
  ];
  for (const [cx, cy, start] of corners) {
    for (let i = 0; i <= 8; i += 1) {
      const a = start + (i / 8) * (Math.PI / 2);
      pts.push(S(o.x + cx + Math.cos(a) * pad, o.y + cy + Math.sin(a) * pad, 0.015));
    }
  }
  pts.push(pts[0].clone());
  return pts;
}

function fovGeometry(fovDeg, range) {
  const half = THREE.MathUtils.degToRad(fovDeg / 2);
  const steps = 24;
  const pos = [0, 0, 0];
  const col = [0.25, 0.76, 0.71, 0.32];
  for (let i = 0; i <= steps; i += 1) {
    const a = -half + (i / steps) * 2 * half;
    // Local robot frame: +x forward, sim +y = three -z.
    pos.push(Math.cos(a) * range, 0, -Math.sin(a) * range);
    col.push(0.25, 0.76, 0.71, 0);
  }
  const idx = [];
  for (let i = 1; i <= steps; i += 1) idx.push(0, i, i + 1);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 4));
  geo.setIndex(idx);
  return geo;
}

// ---------------------------------------------------------------- main class
export class Sim3D {
  constructor(container, world) {
    this.world = world;
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    if (!this.renderer.getContext()) throw new Error('WebGL unavailable');
    // Capped pixel ratio and a 1024 px shadow map keep modest hardware responsive.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.domElement.className = 'sim-canvas sim-3d';
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color('#1b2023');
    this.camera = new THREE.PerspectiveCamera(38, 16 / 9, 0.1, 200);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 45;
    this.controls.maxPolarAngle = THREE.MathUtils.degToRad(80); // never below the floor
    this.controls.screenSpacePanning = false;
    this.controls.addEventListener('change', () => {
      // Keep the orbit target over the map so the scene cannot be lost.
      const t = this.controls.target;
      t.x = THREE.MathUtils.clamp(t.x, -2, world.width + 2);
      t.z = THREE.MathUtils.clamp(t.z, -world.height - 2, 2);
      t.y = 0;
      this.dirty = true;
    });
    this.mode = 'orbit';
    this.M = makeMaterials();
    this.obstacleNodes = new Map(); // id -> { node, signature, born }
    this.layers = {};
    this.raycaster = new THREE.Raycaster();
    this.floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    this.dirty = true;
    this._buildEnvironment();
    this._buildOverlays();
    this.setView('orbit', true);
  }

  _buildEnvironment() {
    const { width: W, height: H } = this.world;
    const hemi = new THREE.HemisphereLight('#fff7ea', '#5c5a55', 0.85);
    const sun = new THREE.DirectionalLight('#fffaf0', 1.9);
    sun.position.set(W * 0.25, 18, -H * 0.05);
    sun.target.position.set(W / 2, 0, -H / 2);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    const sc = sun.shadow.camera;
    sc.left = -W * 0.75;
    sc.right = W * 0.75;
    sc.top = H * 0.9;
    sc.bottom = -H * 0.9;
    sc.near = 1;
    sc.far = 50;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    const fill = new THREE.DirectionalLight('#cfe2ff', 0.35);
    fill.position.set(W, 8, 4);
    this.scene.add(hemi, sun, sun.target, fill);
    this.sun = sun;

    const tex = concreteTexture();
    tex.repeat.set(W / 5, H / 5);
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(W, H),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.92, metalness: 0 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(W / 2, 0, -H / 2);
    floor.receiveShadow = true;
    this.scene.add(floor);

    // Apron around the map so the walls sit on something.
    const apron = new THREE.Mesh(new THREE.PlaneGeometry(W + 8, H + 8), new THREE.MeshStandardMaterial({ color: '#2a2f33', roughness: 1 }));
    apron.rotation.x = -Math.PI / 2;
    apron.position.set(W / 2, -0.005, -H / 2);
    this.scene.add(apron);

    // Perimeter walls with a rubber kick-strip; painted pedestrian line just inside.
    const t = 0.15;
    const wh = 0.55;
    const walls = [
      [W + 2 * t, t, W / 2, -t / 2],
      [W + 2 * t, t, W / 2, H + t / 2],
      [t, H, -t / 2, H / 2],
      [t, H, W + t / 2, H / 2],
    ];
    for (const [w, d, x, y] of walls) {
      this.scene.add(box(w, wh, d, this.M.wall, x, wh / 2, -y));
      this.scene.add(box(w + 0.01, 0.08, d + 0.01, this.M.bumper, x, 0.04, -y));
    }
    const line = 0.05;
    const inset = 0.25;
    for (const [w, d, x, y] of [
      [W - 2 * inset, line, W / 2, inset],
      [W - 2 * inset, line, W / 2, H - inset],
      [line, H - 2 * inset, inset, H / 2],
      [line, H - 2 * inset, W - inset, H / 2],
    ]) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), this.M.paint);
      m.rotation.x = -Math.PI / 2;
      m.position.set(x, 0.003, -y);
      m.receiveShadow = true;
      this.scene.add(m);
    }
  }

  _buildOverlays() {
    this.obstacleGroup = new THREE.Group();
    this.overlayGroup = new THREE.Group();
    this.scene.add(this.obstacleGroup, this.overlayGroup);

    this.routeMat = new THREE.MeshBasicMaterial({ color: '#2fb8ab', transparent: true, opacity: 0.95, depthWrite: false });
    this.ghostMat = new THREE.MeshBasicMaterial({ color: '#e9ecef', transparent: true, opacity: 0.5, depthWrite: false });
    this.route = null;
    this.ghost = null;
    this.waypointGroup = new THREE.Group();
    this.overlayGroup.add(this.waypointGroup);
    this.activeRing = new THREE.Mesh(
      new THREE.RingGeometry(0.13, 0.17, 32),
      new THREE.MeshBasicMaterial({ color: '#2fb8ab', transparent: true, opacity: 0.9, depthWrite: false }),
    );
    this.activeRing.rotation.x = -Math.PI / 2;
    this.activeRing.visible = false;
    this.overlayGroup.add(this.activeRing);

    // Target: floor ring + slim beacon post.
    this.target = new THREE.Group();
    const ringMat = new THREE.MeshBasicMaterial({ color: '#ffc83d', transparent: true, opacity: 0.95, depthWrite: false });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.17, 0.24, 40), ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.014;
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.75, 8), this.M.dark);
    post.position.y = 0.375;
    const beaconMat = new THREE.MeshStandardMaterial({ color: '#ffc83d', emissive: '#ffb000', emissiveIntensity: 0.6 });
    const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12), beaconMat);
    beacon.position.y = 0.77;
    this.target.add(ring, post, beacon);
    this.targetRingMat = ringMat;
    this.target.visible = false;
    this.overlayGroup.add(this.target);

    const r = buildRobot(this.M);
    this.robot = r.group;
    this.wheels = r.wheels;
    this.ledMat = r.ledMat;
    this.scene.add(this.robot);
    this.footprint = new THREE.Mesh(
      new THREE.RingGeometry(0.295, 0.31, 48),
      new THREE.MeshBasicMaterial({ color: '#ff5d4f', transparent: true, opacity: 0, depthWrite: false }),
    );
    this.footprint.rotation.x = -Math.PI / 2;
    this.footprint.position.y = 0.016;
    this.robot.add(this.footprint);

    this.fov = null;
    // Simulated LiDAR returns, rebuilt only when a new scan frame arrives.
    this.lidarPoints = new THREE.Points(
      new THREE.BufferGeometry(),
      new THREE.PointsMaterial({ size: 0.07, vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false }),
    );
    this.lidarPoints.renderOrder = 6;
    this.overlayGroup.add(this.lidarPoints);
    this.lidarFrame = null;
    this.trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#c4d0d6', transparent: true, opacity: 0.7 }));
    this.overlayGroup.add(this.trail);
    this.inflationGroup = new THREE.Group();
    this.overlayGroup.add(this.inflationGroup);
    this.highlightGroup = new THREE.Group();
    this.overlayGroup.add(this.highlightGroup);
    this.trackGroup = new THREE.Group();
    this.overlayGroup.add(this.trackGroup);
    this.detectGroup = new THREE.Group();
    this.overlayGroup.add(this.detectGroup);
    this.rejectMarker = new THREE.Group();
    const xMat = new THREE.MeshBasicMaterial({ color: '#ff5d4f', transparent: true, depthWrite: false });
    for (const a of [Math.PI / 4, -Math.PI / 4]) {
      const bar = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.06), xMat);
      bar.rotation.set(-Math.PI / 2, 0, a);
      bar.position.y = 0.02;
      this.rejectMarker.add(bar);
    }
    this.rejectMat = xMat;
    this.rejectMarker.visible = false;
    this.overlayGroup.add(this.rejectMarker);
  }

  // ------------------------------------------------------------- camera
  _fitDistance() {
    const { width: W, height: H } = this.world;
    const vfov = THREE.MathUtils.degToRad(this.camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect);
    return Math.max((W * 0.56) / Math.tan(hfov / 2), (H * 0.62) / Math.tan(vfov / 2));
  }

  setView(mode, instant = false) {
    const { width: W, height: H } = this.world;
    this.mode = mode;
    const center = new THREE.Vector3(W / 2, 0, -H / 2);
    const d = this._fitDistance();
    this.controls.enableRotate = mode !== 'top';
    if (mode === 'top') {
      this.camera.up.set(0, 0, -1);
      this.camera.position.set(center.x, d * 0.98, center.z + 0.001);
    } else {
      this.camera.up.set(0, 1, 0);
      const elev = THREE.MathUtils.degToRad(mode === 'follow' ? 62 : 52);
      const dist = mode === 'follow' ? 8.5 : d * 0.98;
      this.camera.position.set(center.x, Math.sin(elev) * dist, center.z + Math.cos(elev) * dist);
    }
    this.controls.target.copy(center);
    if (mode === 'follow' && this.robot) {
      const off = this.camera.position.clone().sub(center);
      this.controls.target.set(this.robot.position.x, 0, this.robot.position.z);
      this.camera.position.copy(this.controls.target).add(off);
    }
    this.controls.update();
    this.dirty = true;
    if (instant) this.controls.update();
  }

  zoom(factor) {
    const off = this.camera.position.clone().sub(this.controls.target);
    const len = THREE.MathUtils.clamp(off.length() * factor, this.controls.minDistance, this.controls.maxDistance);
    off.setLength(len);
    this.camera.position.copy(this.controls.target).add(off);
    this.controls.update();
    this.dirty = true;
  }

  resize(w, h) {
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = `${w}px`;
    this.renderer.domElement.style.height = `${h}px`;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  /** Pointer -> { point: {x, y} in sim metres | null, obstacleId | null }. */
  pick(clientX, clientY) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.obstacleGroup.children, true)[0];
    const p = new THREE.Vector3();
    const onFloor = this.raycaster.ray.intersectPlane(this.floorPlane, p);
    const point =
      onFloor && p.x >= 0 && p.x <= this.world.width && -p.z >= 0 && -p.z <= this.world.height
        ? { x: Math.round(p.x * 100) / 100, y: Math.round(-p.z * 100) / 100 }
        : null;
    return { point, obstacleId: hit?.object.userData.obstacleId ?? null };
  }

  /** Project a sim point to canvas pixels (used by tests and labels). */
  project(x, y) {
    const v = S(x, y).project(this.camera);
    const rect = this.renderer.domElement.getBoundingClientRect();
    return { x: ((v.x + 1) / 2) * rect.width, y: ((1 - v.y) / 2) * rect.height };
  }

  // ------------------------------------------------------------- per-frame sync
  _syncObstacles(obstacles, now, effects) {
    const seen = new Set();
    for (const o of obstacles) {
      seen.add(o.id);
      const sig = `${o.label}|${o.shape}|${o.w}|${o.h}|${o.r}|${o.height}`;
      let entry = this.obstacleNodes.get(o.id);
      if (entry && entry.signature !== sig) {
        this.obstacleGroup.remove(entry.node);
        disposeTree(entry.node);
        entry = null;
      }
      if (!entry) {
        const node = buildObstacle(o, this.M);
        if (o.dynamic || o.label === 'person') {
          const label = textSprite(o.id, { height: 0.24 });
          label.position.y = o.height + 0.3;
          node.add(label);
        }
        this.obstacleGroup.add(node);
        entry = { node, signature: sig, born: this.initialised && effects ? now : 0, last: null };
        this.obstacleNodes.set(o.id, entry);
      }
      const { node } = entry;
      node.position.set(o.x, 0, -o.y);
      if (o.label === 'person' && entry.last) {
        const dx = o.x - entry.last.x;
        const dy = o.y - entry.last.y;
        if (Math.hypot(dx, dy) > 0.002) node.rotation.y = Math.atan2(dy, dx);
      }
      entry.last = { x: o.x, y: o.y };
      const age = entry.born ? (now - entry.born) / APPEAR_MS : 1;
      const s = age >= 1 ? 1 : 0.5 + 0.5 * (1 - (1 - Math.max(age, 0)) ** 3);
      node.scale.set(1, s, 1);
      if (age < 1) this.dirty = true;
    }
    for (const [id, entry] of this.obstacleNodes) {
      if (!seen.has(id)) {
        this.obstacleGroup.remove(entry.node);
        disposeTree(entry.node);
        this.obstacleNodes.delete(id);
      }
    }
    this.initialised = true;
  }

  _syncRoute(t, anim, now, effects, visible) {
    if (this.routeVersion !== anim.pathVersion || this.routeLen !== t.path.length) {
      this.routeVersion = anim.pathVersion;
      this.routeLen = t.path.length;
      if (this.route) {
        this.overlayGroup.remove(this.route);
        this.route.geometry.dispose();
        this.route = null;
      }
      this.waypointGroup.clear();
      if (t.path.length > 1) {
        this.route = new THREE.Mesh(ribbonGeometry(t.path, 0.09), this.routeMat);
        this.route.renderOrder = 3;
        this.overlayGroup.add(this.route);
        const disc = new THREE.CircleGeometry(0.06, 20);
        const mat = new THREE.MeshBasicMaterial({ color: '#e9fbf8', depthWrite: false });
        t.path.slice(1).forEach(([x, y]) => {
          const m = new THREE.Mesh(disc, mat);
          m.rotation.x = -Math.PI / 2;
          m.position.copy(S(x, y, ROUTE_Y + 0.002));
          m.renderOrder = 4;
          this.waypointGroup.add(m);
        });
      }
    }
    if (this.route) {
      this.route.visible = visible;
      const segs = this.route.geometry.userData.segments;
      const f = effects ? Math.min(1, (now - anim.revealStart) / REVEAL_MS) : 1;
      this.route.geometry.setDrawRange(0, Math.ceil(segs * (1 - (1 - f) ** 3)) * 6);
      if (f < 1) this.dirty = true;
    }
    this.waypointGroup.visible = visible;
    const wp = t.current_waypoint;
    this.activeRing.visible = visible && !!wp;
    if (wp) {
      this.activeRing.position.copy(S(wp.x, wp.y, ROUTE_Y + 0.003));
      const pulse = effects ? 1 + 0.12 * Math.sin(now / 220) : 1;
      this.activeRing.scale.setScalar(pulse);
    }

    // Previous route, only after a genuine replan reported by the backend.
    if (anim.ghost !== this.ghostSource) {
      this.ghostSource = anim.ghost;
      if (this.ghost) {
        this.overlayGroup.remove(this.ghost);
        this.ghost.geometry.dispose();
        this.ghost = null;
      }
      if (anim.ghost && anim.ghost.length > 1) {
        this.ghost = new THREE.Mesh(ribbonGeometry(anim.ghost, 0.06), this.ghostMat);
        this.ghost.position.y = -0.002;
        this.overlayGroup.add(this.ghost);
      }
    }
    if (this.ghost) {
      const age = (now - anim.ghostStart) / GHOST_MS;
      this.ghost.visible = visible && age < 1;
      this.ghostMat.opacity = 0.55 * Math.max(0, 1 - age);
      if (age < 1) this.dirty = true;
    }
  }

  _syncInflation(t, obstacles, visible) {
    const key = visible ? `${t.safety.inflation}|${obstacles.map((o) => `${o.id}:${o.x.toFixed(2)},${o.y.toFixed(2)}`).join(';')}` : 'off';
    if (key === this.inflationKey) return;
    this.inflationKey = key;
    this.inflationGroup.children.forEach((c) => c.geometry.dispose());
    this.inflationGroup.clear();
    if (!visible) return;
    const mat = new THREE.LineDashedMaterial({ color: '#ff8a7a', dashSize: 0.12, gapSize: 0.09, transparent: true, opacity: 0.75 });
    for (const o of obstacles) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(outlinePoints(o, t.safety.inflation)), mat);
      line.computeLineDistances();
      this.inflationGroup.add(line);
    }
  }

  _syncSensor(t, pose, visible) {
    const cam = t.perception?.camera;
    if (!this.fov && cam) {
      this.fov = new THREE.Mesh(
        fovGeometry(cam.fov_deg, cam.range),
        new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide }),
      );
      this.fov.renderOrder = 2;
      this.fovOffset = cam.forward_offset;
      this.overlayGroup.add(this.fov);
    }
    if (this.fov) {
      this.fov.visible = visible && t.perception.enabled;
      const off = this.fovOffset;
      this.fov.position.set(pose.x + Math.cos(pose.theta) * off, 0.008, -(pose.y + Math.sin(pose.theta) * off));
      this.fov.rotation.y = pose.theta;
    }

    // Objects currently reported by the detector. Simulated detections carry object ids;
    // YOLOv8 detections do not, so nothing is outlined for them here.
    const ids = visible ? (t.perception?.detections || []).map((d) => d.object_id).filter(Boolean) : [];
    const key = ids.join(',');
    if (key !== this.detectKey) {
      this.detectKey = key;
      this.detectGroup.children.forEach((c) => c.geometry.dispose());
      this.detectGroup.clear();
      const mat = new THREE.LineBasicMaterial({ color: '#7fe3d9', transparent: true, opacity: 0.85 });
      for (const id of ids) {
        const o = t.obstacles.find((ob) => ob.id === id);
        if (!o) continue;
        const w = o.shape === 'circle' ? o.r * 2 : o.w;
        const d = o.shape === 'circle' ? o.r * 2 : o.h;
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w + 0.08, o.height + 0.06, d + 0.08)), mat);
        edges.position.set(o.x, (o.height + 0.06) / 2, -o.y);
        edges.userData.id = id;
        this.detectGroup.add(edges);
      }
    }
    for (const e of this.detectGroup.children) {
      const o = t.obstacles.find((ob) => ob.id === e.userData.id);
      if (o) e.position.set(o.x, e.position.y, -o.y);
    }

    const tracks = visible ? t.perception?.tracks || [] : [];
    const tkey = tracks.map((tr) => `${tr.id}:${tr.x},${tr.y},${tr.stale}`).join(';');
    if (tkey !== this.trackKey) {
      this.trackKey = tkey;
      this.trackGroup.children.forEach((c) => c.geometry?.dispose());
      this.trackGroup.clear();
      const geo = new THREE.OctahedronGeometry(0.09);
      for (const tr of tracks) {
        const m = new THREE.Mesh(
          geo,
          new THREE.MeshBasicMaterial({ color: '#ff8a7a', transparent: true, opacity: tr.stale ? 0.35 : 0.95 }),
        );
        m.position.set(tr.x, 0.25, -tr.y);
        this.trackGroup.add(m);
      }
    }
  }

  _syncHighlights(obstacles, anim, now, selectedObstacle) {
    this.highlightGroup.children.forEach((c) => {
      c.geometry.dispose();
      c.material.dispose();
    });
    this.highlightGroup.clear();
    for (const o of obstacles) {
      const started = anim.highlights.get(o.id);
      const age = started ? (now - started) / HIGHLIGHT_MS : 2;
      const selected = o.id === selectedObstacle;
      if (age >= 1 && !selected) continue;
      const w = (o.shape === 'circle' ? o.r * 2 : o.w) + 0.16;
      const d = (o.shape === 'circle' ? o.r * 2 : o.h) + 0.16;
      const mat = new THREE.LineBasicMaterial({
        color: selected ? '#ffc83d' : '#ff5d4f',
        transparent: true,
        opacity: selected ? 1 : 1 - age,
      });
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, o.height + 0.1, d)), mat);
      edges.position.set(o.x, (o.height + 0.1) / 2, -o.y);
      this.highlightGroup.add(edges);
      if (!selected) this.dirty = true;
    }
  }

  _syncLidar(t, visible) {
    const lidar = t.sensors?.sensors?.find((s) => s.key === 'lidar');
    const reading = lidar?.enabled ? lidar.reading : null;
    this.lidarPoints.visible = visible && !!reading;
    if (!visible || !reading || reading.frame === this.lidarFrame) return;
    this.lidarFrame = reading.frame;
    const r = t.robot;
    const h = lidar.config.mount_height ?? 0.32;
    const pos = [];
    const col = [];
    for (const [bearing, range] of reading.scan) {
      if (range === null) continue;
      const a = r.theta + (bearing * Math.PI) / 180;
      pos.push(r.x + range * Math.cos(a), h, -(r.y + range * Math.sin(a)));
      const near = range - 0.3 < 0.9; // within the slow-down distance of the robot surface
      col.push(...(near ? [1, 0.55, 0.25] : [0.5, 0.92, 0.86]));
    }
    this.lidarPoints.geometry.dispose();
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    this.lidarPoints.geometry = geo;
    this.dirty = true;
  }

  /** Apply one frame of interpolated state. */
  update(state, opts, now) {
    const { layers, effects, rejected, selectedObstacle, anim } = opts;
    if (!state) return;
    const { t, pose, obstacles } = state;
    this._syncObstacles(obstacles, now, effects);

    // Robot pose and wheel spin (differential drive: v +/- w * track/2).
    const prev = this.lastPose;
    this.robot.position.set(pose.x, 0, -pose.y);
    this.robot.rotation.y = pose.theta;
    if (prev) {
      const ds = Math.hypot(pose.x - prev.x, pose.y - prev.y);
      let dth = pose.theta - prev.theta;
      dth = Math.atan2(Math.sin(dth), Math.cos(dth));
      const dir = Math.sign(Math.cos(Math.atan2(pose.y - prev.y, pose.x - prev.x) - pose.theta)) || 1;
      for (const { wheel, side } of this.wheels) {
        const dist = dir * ds + side * dth * 0.276;
        wheel.rotation.z -= dist / 0.075;
      }
      if (ds > 1e-4 || Math.abs(dth) > 1e-4) this.dirty = true;
    }
    this.lastPose = { x: pose.x, y: pose.y, theta: pose.theta };
    this.ledMat.color.set(LED[t.mission.status] || LED.idle);
    this.ledMat.emissive.set(LED[t.mission.status] || LED.idle);
    // Footprint ring: red on a ground-truth clearance warning or a sensor stop, amber while slowing.
    const prox = t.sensors?.proximity?.action;
    const ringColor = t.safety?.warning || prox === 'stop' ? '#ff5d4f' : prox === 'slow' || prox === 'degraded' ? '#f0b429' : null;
    this.footprint.material.opacity = ringColor ? 0.9 : 0;
    if (ringColor) this.footprint.material.color.set(ringColor);
    this._syncLidar(t, layers.lidar);

    if (this.mode === 'follow') {
      const target = new THREE.Vector3(pose.x, 0, -pose.y);
      const delta = target.clone().sub(this.controls.target);
      this.controls.target.add(delta);
      this.camera.position.add(delta);
    }

    this._syncRoute(t, anim, now, effects, layers.route);
    this.target.visible = !!t.target;
    if (t.target) {
      this.target.position.set(t.target.x, 0, -t.target.y);
      this.targetRingMat.color.set(t.mission.status === 'goal_reached' ? '#5fd38d' : '#ffc83d');
    }
    this._syncInflation(t, obstacles, layers.inflation);
    this._syncSensor(t, pose, layers.sensor);
    this._syncHighlights(obstacles, anim, now, selectedObstacle);

    // Trail of recent positions.
    // Keyed on the newest point: the length alone stops changing once the trail is capped,
    // and a reset must clear the old trail even if the robot never moves again.
    this.trail.visible = layers.trail;
    const newest = anim.trail[anim.trail.length - 1] ?? null;
    if (layers.trail && newest !== this.trailNewest) {
      this.trailNewest = newest;
      this.trail.geometry.dispose();
      const pts = anim.trail.length > 1 ? anim.trail.map(([x, y]) => S(x, y, 0.01)) : [];
      this.trail.geometry = new THREE.BufferGeometry().setFromPoints(pts);
      this.dirty = true;
    }

    // Rejected target marker.
    const rAge = rejected ? (now - rejected.at) / 1800 : 2;
    this.rejectMarker.visible = rAge < 1;
    if (rAge < 1) {
      this.rejectMarker.position.set(rejected.x, 0, -rejected.y);
      this.rejectMat.opacity = 1 - rAge;
      this.dirty = true;
    }
  }

  /** Demo mode: native pixel ratio of 1 and no shadow pass, roughly halving GPU work per frame. */
  setQuality(lite) {
    if (this.lite === lite) return;
    this.lite = lite;
    this.renderer.setPixelRatio(lite ? 1 : Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.shadowMap.enabled = !lite;
    this.sun.castShadow = !lite;
    this.dirty = true;
  }

  render() {
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
  }

  dispose() {
    this.controls.dispose();
    disposeTree(this.scene);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
