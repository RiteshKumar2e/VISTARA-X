// Top-down renderer for the simulation map. It only visualises state received from
// the backend: poses are interpolated between the last two telemetry samples (never
// extrapolated), so nothing is drawn where the backend has not reported it.
// World frame: metres, origin bottom-left, +y up.

export const FOV_DEG = 70;
const CAMERA_RANGE = 4; // metres drawn for the camera cone (display only)
const REVEAL_MS = 700;
const GHOST_MS = 2600;
const APPEAR_MS = 500;
const HIGHLIGHT_MS = 2500;
const MARGIN = { left: 28, right: 10, top: 10, bottom: 22 };

export function readPalette(el) {
  const s = getComputedStyle(el);
  const v = (name) => s.getPropertyValue(name).trim();
  return {
    bg: v('--sim-bg'),
    floor: v('--sim-floor'),
    grid: v('--sim-grid'),
    gridMajor: v('--sim-grid-major'),
    wall: v('--sim-wall'),
    unknown: v('--sim-unknown'),
    static: v('--sim-static'),
    staticTop: v('--sim-static-top'),
    dynamic: v('--sim-dynamic'),
    dynamicEdge: v('--sim-dynamic-edge'),
    person: v('--sim-person'),
    inflation: v('--sim-inflation'),
    path: v('--sim-path'),
    ghost: v('--sim-ghost'),
    trail: v('--sim-trail'),
    robot: v('--sim-robot'),
    robotEdge: v('--sim-robot-edge'),
    wheel: v('--sim-wheel'),
    fov: v('--sim-fov'),
    track: v('--sim-track'),
    target: v('--sim-target'),
    danger: v('--sim-danger'),
    text: v('--sim-text'),
    label: v('--sim-label'),
  };
}

/** View transform: base fit + user zoom/pan (zoom about a screen point). */
export function makeView(cssWidth, world, zoom = 1, pan = { x: 0, y: 0 }) {
  const narrow = cssWidth < 520;
  const m = { ...MARGIN, left: narrow ? 20 : MARGIN.left, bottom: narrow ? 18 : MARGIN.bottom };
  const fit = (cssWidth - m.left - m.right) / world.width;
  const cssHeight = Math.round(world.height * fit + m.top + m.bottom);
  const scale = fit * zoom;
  const ox = m.left + pan.x;
  const oy = m.top + pan.y;
  return {
    m,
    fit,
    scale,
    zoom,
    cssWidth,
    cssHeight,
    narrow,
    X: (x) => ox + x * scale,
    Y: (y) => oy + (world.height - y) * scale,
    toWorld: (px, py) => ({ x: (px - ox) / scale, y: world.height - (py - oy) / scale }),
  };
}

/** Clamp pan so the map cannot be dragged completely out of view. */
export function clampPan(pan, zoom, cssWidth, cssHeight, world) {
  const fit = (cssWidth - MARGIN.left - MARGIN.right) / world.width;
  const w = world.width * fit * zoom;
  const h = world.height * fit * zoom;
  const viewW = cssWidth - MARGIN.left - MARGIN.right;
  const viewH = cssHeight - MARGIN.top - MARGIN.bottom;
  return {
    x: Math.min(0, Math.max(viewW - w, pan.x)),
    y: Math.min(0, Math.max(viewH - h, pan.y)),
  };
}

const lerp = (a, b, t) => a + (b - a) * t;
const lerpAngle = (a, b, t) => {
  let d = b - a;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  return a + d * t;
};
const easeOut = (t) => 1 - (1 - t) ** 3;

function pathLength(path) {
  let L = 0;
  for (let i = 1; i < path.length; i += 1) L += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
  return L;
}

function partialPath(path, fraction) {
  if (fraction >= 1) return path;
  const target = pathLength(path) * fraction;
  const out = [path[0]];
  let acc = 0;
  for (let i = 1; i < path.length; i += 1) {
    const seg = Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
    if (acc + seg >= target) {
      const f = seg ? (target - acc) / seg : 0;
      out.push([lerp(path[i - 1][0], path[i][0], f), lerp(path[i - 1][1], path[i][1], f)]);
      return out;
    }
    acc += seg;
    out.push(path[i]);
  }
  return out;
}

/**
 * Keeps per-frame visual state derived from telemetry: interpolation samples,
 * route reveal, previous-route ghost, obstacle appearance and event highlights.
 */
export class SceneAnimator {
  constructor() {
    this.prev = null;
    this.curr = null;
    this.prevAt = 0;
    this.currAt = 0;
    this.pathVersion = null;
    this.revealStart = 0;
    this.ghost = null;
    this.ghostStart = 0;
    this.seenObstacles = new Map(); // id -> first seen time
    this.highlights = new Map(); // obstacle id -> start time
    this.seenEvents = null;
    this.wheelPhase = 0;
    this.lastDisplay = null;
    this.trail = [];
    this.trailKey = null;
  }

  ingest(t, now) {
    if (!t || t === this.curr) return;
    const reset = this.curr && (t.scenario !== this.curr.scenario || t.sim_time < this.curr.sim_time);
    this.prev = reset ? t : this.curr || t;
    this.prevAt = reset ? now : this.currAt || now;
    this.curr = t;
    this.currAt = now;

    if (this.pathVersion !== t.path_version || reset) {
      const old = this.prev?.path;
      if (!reset && old && old.length > 1 && this.pathVersion !== null && t.path.length > 1) {
        this.ghost = old;
        this.ghostStart = now;
      }
      this.pathVersion = t.path_version;
      this.revealStart = now;
    }
    if (reset) {
      this.seenObstacles.clear();
      this.ghost = null;
    }
    for (const o of t.obstacles) if (!this.seenObstacles.has(o.id)) this.seenObstacles.set(o.id, this.seenEvents ? now : 0);

    // Highlight the obstacle named in a real backend obstruction/replan event.
    if (this.seenEvents === null) {
      this.seenEvents = new Set(t.events.map((e) => e.id));
    } else {
      for (const e of t.events) {
        if (this.seenEvents.has(e.id)) continue;
        this.seenEvents.add(e.id);
        if (e.type === 'obstruction' || e.type === 'safety_stop') {
          const id = e.data?.obstacle || /by ([\w-]+)/.exec(e.message)?.[1];
          if (id) this.highlights.set(id, now);
        }
      }
    }

    const key = `${t.scenario}:${t.mission.id}`;
    if (key !== this.trailKey || reset) {
      this.trailKey = key;
      this.trail = [];
    }
  }

  /** Interpolated display state for the current frame. */
  frame(now, smooth) {
    const t = this.curr;
    if (!t) return null;
    const span = Math.max(this.currAt - this.prevAt, 1);
    const f = smooth && this.prev ? Math.min(1, Math.max(0, (now - this.currAt) / span)) : 1;
    const a = smooth && this.prev ? this.prev : t;
    const pose = {
      ...t.robot,
      x: lerp(a.robot.x, t.robot.x, f),
      y: lerp(a.robot.y, t.robot.y, f),
      theta: lerpAngle(a.robot.theta, t.robot.theta, f),
    };
    if (this.lastDisplay) {
      const moved = Math.hypot(pose.x - this.lastDisplay.x, pose.y - this.lastDisplay.y);
      const turned = lerpAngle(this.lastDisplay.theta, pose.theta, 1) - this.lastDisplay.theta;
      this.wheelPhase += moved * 40 + Math.abs(turned) * 6;
    }
    this.lastDisplay = pose;
    const last = this.trail[this.trail.length - 1];
    if (!last || Math.hypot(last[0] - pose.x, last[1] - pose.y) > 0.05) {
      this.trail.push([pose.x, pose.y]);
      if (this.trail.length > 600) this.trail.shift();
    }
    const prevObs = new Map((a.obstacles || []).map((o) => [o.id, o]));
    const obstacles = t.obstacles.map((o) => {
      const p = prevObs.get(o.id);
      return p && o.moving ? { ...o, x: lerp(p.x, o.x, f), y: lerp(p.y, o.y, f) } : o;
    });
    return { t, pose, obstacles };
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function drawRobot(ctx, view, pose, pal, wheelPhase, warning) {
  const { X, Y, scale } = view;
  const cx = X(pose.x);
  const cy = Y(pose.y);
  const r = Math.max(pose.radius * scale, 7);
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-pose.theta);
  if (warning) {
    ctx.strokeStyle = pal.danger;
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.arc(0, 0, r * 1.45, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  // Wheels (two drive wheels on the axle), with tread lines moving with travel.
  const ww = r * 0.9;
  const wh = r * 0.32;
  for (const side of [-1, 1]) {
    const wy = side * r * 0.86 - wh / 2;
    ctx.fillStyle = pal.wheel;
    roundRect(ctx, -ww / 2, wy, ww, wh, wh * 0.3);
    ctx.fill();
    if (r > 9) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(-ww / 2, wy, ww, wh);
      ctx.clip();
      ctx.strokeStyle = 'rgba(255,255,255,0.28)';
      ctx.lineWidth = 1;
      const step = ww / 4;
      const off = (wheelPhase % step) - step;
      for (let x = -ww / 2 + off; x < ww / 2 + step; x += step) {
        ctx.beginPath();
        ctx.moveTo(x, wy);
        ctx.lineTo(x, wy + wh);
        ctx.stroke();
      }
      ctx.restore();
    }
  }
  // Body.
  ctx.fillStyle = pal.robot;
  ctx.strokeStyle = pal.robotEdge;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(0, 0, r * 0.78, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  // Sensor head at the front and heading indicator.
  ctx.fillStyle = pal.path;
  roundRect(ctx, r * 0.36, -r * 0.22, r * 0.34, r * 0.44, 2);
  ctx.fill();
  ctx.strokeStyle = pal.robot;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(r * 0.78, 0);
  ctx.lineTo(r * 1.35, 0);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(r * 1.55, 0);
  ctx.lineTo(r * 1.25, -r * 0.18);
  ctx.lineTo(r * 1.25, r * 0.18);
  ctx.closePath();
  ctx.fillStyle = pal.robot;
  ctx.fill();
  ctx.restore();
}

export function drawScene(ctx, view, world, state, opts) {
  const { pal, layers, explored, now, anim, effects, rejected, selectedObstacle } = opts;
  const { X, Y, scale, m, narrow, cssWidth, cssHeight } = view;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.fillStyle = pal.bg;
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  ctx.save();
  ctx.beginPath();
  ctx.rect(m.left, m.top, cssWidth - m.left - m.right, cssHeight - m.top - m.bottom);
  ctx.clip();

  ctx.fillStyle = pal.floor;
  ctx.fillRect(X(0), Y(world.height), world.width * scale, world.height * scale);

  if (layers.explored && explored) {
    const res = explored.resolution;
    ctx.fillStyle = pal.unknown;
    explored.cells.forEach((row, r) => {
      for (let c = 0; c < row.length; c += 1) {
        if (row[c] === '?') ctx.fillRect(X(c * res), Y((r + 1) * res), res * scale + 0.5, res * scale + 0.5);
      }
    });
  }

  // Floor grid: 1 m lines, stronger every 5 m.
  ctx.lineWidth = 1;
  for (let x = 1; x < world.width; x += 1) {
    ctx.strokeStyle = x % 5 ? pal.grid : pal.gridMajor;
    ctx.beginPath();
    ctx.moveTo(Math.round(X(x)) + 0.5, Y(world.height));
    ctx.lineTo(Math.round(X(x)) + 0.5, Y(0));
    ctx.stroke();
  }
  for (let y = 1; y < world.height; y += 1) {
    ctx.strokeStyle = y % 5 ? pal.grid : pal.gridMajor;
    ctx.beginPath();
    ctx.moveTo(X(0), Math.round(Y(y)) + 0.5);
    ctx.lineTo(X(world.width), Math.round(Y(y)) + 0.5);
    ctx.stroke();
  }
  // Boundary walls.
  ctx.strokeStyle = pal.wall;
  ctx.lineWidth = Math.max(3, 0.12 * scale);
  ctx.strokeRect(X(0), Y(world.height), world.width * scale, world.height * scale);

  if (state) {
    const { t, pose, obstacles } = state;
    const inflation = t.safety?.inflation ?? 0.45;

    if (layers.inflation) {
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = pal.inflation;
      ctx.lineWidth = 1;
      for (const o of obstacles) {
        ctx.beginPath();
        if (o.shape === 'circle') ctx.arc(X(o.x), Y(o.y), (o.r + inflation) * scale, 0, Math.PI * 2);
        else {
          const r = inflation * scale;
          ctx.roundRect(X(o.x - o.w / 2) - r, Y(o.y + o.h / 2) - r, o.w * scale + 2 * r, o.h * scale + 2 * r, r);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    // Obstacles: ground-truth geometry from the simulator.
    for (const o of obstacles) {
      const born = anim.seenObstacles.get(o.id) || 0;
      const age = effects ? (now - born) / APPEAR_MS : 1;
      const grow = born ? easeOut(Math.min(1, Math.max(0, age))) : 1;
      const isPerson = o.label === 'person';
      ctx.save();
      ctx.globalAlpha = 0.25 + 0.75 * grow;
      if (o.shape === 'circle') {
        const rr = o.r * scale * (0.6 + 0.4 * grow);
        ctx.fillStyle = isPerson ? pal.person : o.dynamic ? pal.dynamic : pal.static;
        ctx.beginPath();
        ctx.arc(X(o.x), Y(o.y), rr, 0, Math.PI * 2);
        ctx.fill();
        if (isPerson) {
          ctx.fillStyle = pal.robot;
          ctx.beginPath();
          ctx.arc(X(o.x), Y(o.y), rr * 0.45, 0, Math.PI * 2);
          ctx.fill();
        }
      } else {
        const w = o.w * scale;
        const h = o.h * scale;
        const sx = X(o.x) - (w * (0.6 + 0.4 * grow)) / 2;
        const sy = Y(o.y) - (h * (0.6 + 0.4 * grow)) / 2;
        const sw = w * (0.6 + 0.4 * grow);
        const sh = h * (0.6 + 0.4 * grow);
        ctx.fillStyle = o.dynamic ? pal.dynamic : pal.static;
        ctx.fillRect(sx, sy, sw, sh);
        if (!o.dynamic) {
          // Shelving/pallet top highlight gives a sense of height.
          ctx.fillStyle = pal.staticTop;
          const inset = Math.min(sw, sh) * 0.18;
          ctx.fillRect(sx + inset, sy + inset, sw - 2 * inset, sh - 2 * inset);
        } else {
          ctx.strokeStyle = pal.dynamicEdge;
          ctx.lineWidth = 2;
          ctx.strokeRect(sx + 1, sy + 1, sw - 2, sh - 2);
        }
      }
      ctx.restore();

      const hl = anim.highlights.get(o.id);
      const hlAge = hl ? (now - hl) / HIGHLIGHT_MS : 2;
      if (hlAge < 1 || o.id === selectedObstacle) {
        ctx.save();
        ctx.strokeStyle = o.id === selectedObstacle ? pal.target : pal.danger;
        ctx.lineWidth = 2.5;
        ctx.globalAlpha = o.id === selectedObstacle ? 1 : 1 - hlAge;
        const pad = 6 + (effects && o.id !== selectedObstacle ? 6 * hlAge : 0);
        if (o.shape === 'circle') {
          ctx.beginPath();
          ctx.arc(X(o.x), Y(o.y), o.r * scale + pad, 0, Math.PI * 2);
          ctx.stroke();
        } else {
          ctx.strokeRect(X(o.x - o.w / 2) - pad, Y(o.y + o.h / 2) - pad, o.w * scale + 2 * pad, o.h * scale + 2 * pad);
        }
        ctx.restore();
      }
      if (!narrow && (o.dynamic || isPerson)) {
        ctx.fillStyle = pal.label;
        ctx.font = '11px -apple-system, "Segoe UI", sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        const top = o.shape === 'circle' ? o.y + o.r : o.y + o.h / 2;
        ctx.fillText(o.id, X(o.x) + 6, Y(top) - 3);
      }
    }

    if (layers.tracks) {
      for (const tr of t.perception?.tracks || []) {
        const cx = X(tr.x);
        const cy = Y(tr.y);
        ctx.strokeStyle = pal.track;
        ctx.lineWidth = 1.5;
        ctx.setLineDash(tr.stale ? [2, 3] : []);
        ctx.beginPath();
        ctx.moveTo(cx - 5, cy - 5);
        ctx.lineTo(cx + 5, cy + 5);
        ctx.moveTo(cx + 5, cy - 5);
        ctx.lineTo(cx - 5, cy + 5);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    if (layers.fov) {
      const half = ((FOV_DEG / 2) * Math.PI) / 180;
      const grad = ctx.createRadialGradient(X(pose.x), Y(pose.y), 0, X(pose.x), Y(pose.y), CAMERA_RANGE * scale);
      grad.addColorStop(0, pal.fov);
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(X(pose.x), Y(pose.y));
      ctx.arc(X(pose.x), Y(pose.y), CAMERA_RANGE * scale, -pose.theta - half, -pose.theta + half);
      ctx.closePath();
      ctx.fill();
    }

    if (layers.trail && anim.trail.length > 1) {
      ctx.lineCap = 'round';
      for (let i = 1; i < anim.trail.length; i += 1) {
        ctx.strokeStyle = pal.trail;
        ctx.globalAlpha = 0.15 + 0.85 * (i / anim.trail.length);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(X(anim.trail[i - 1][0]), Y(anim.trail[i - 1][1]));
        ctx.lineTo(X(anim.trail[i][0]), Y(anim.trail[i][1]));
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // Previous route, fading out after a genuine replan.
    if (anim.ghost && effects !== null) {
      const age = (now - anim.ghostStart) / GHOST_MS;
      if (age < 1) {
        ctx.save();
        ctx.globalAlpha = 1 - age;
        ctx.strokeStyle = pal.ghost;
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 5]);
        ctx.beginPath();
        anim.ghost.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
        ctx.stroke();
        ctx.restore();
      } else {
        anim.ghost = null;
      }
    }

    // Current A* route (revealed progressively after each new plan).
    const path = t.path || [];
    if (path.length > 1) {
      const reveal = effects ? easeOut(Math.min(1, (now - anim.revealStart) / REVEAL_MS)) : 1;
      const shown = partialPath(path, reveal);
      ctx.strokeStyle = pal.path;
      ctx.lineWidth = 3;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      shown.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.stroke();
      const current = t.current_waypoint?.index;
      path.forEach(([x, y], i) => {
        if (i === 0 || (reveal < 1 && i >= shown.length)) return;
        const active = i === current;
        ctx.beginPath();
        ctx.arc(X(x), Y(y), active ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = active ? pal.path : pal.floor;
        ctx.fill();
        ctx.strokeStyle = pal.path;
        ctx.lineWidth = 2;
        ctx.stroke();
        if (active) {
          ctx.beginPath();
          ctx.arc(X(x), Y(y), 10, 0, Math.PI * 2);
          ctx.strokeStyle = pal.path;
          ctx.globalAlpha = 0.45;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
      });
    }

    // Target marker.
    if (t.target) {
      const tx = X(t.target.x);
      const ty = Y(t.target.y);
      const reached = t.mission?.status === 'goal_reached';
      ctx.strokeStyle = pal.target;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(tx, ty, Math.max(0.2 * scale, 7), 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(tx - 12, ty);
      ctx.lineTo(tx - 5, ty);
      ctx.moveTo(tx + 5, ty);
      ctx.lineTo(tx + 12, ty);
      ctx.moveTo(tx, ty - 12);
      ctx.lineTo(tx, ty - 5);
      ctx.moveTo(tx, ty + 5);
      ctx.lineTo(tx, ty + 12);
      ctx.stroke();
      if (reached) {
        ctx.fillStyle = pal.path;
        ctx.beginPath();
        ctx.arc(tx, ty, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    drawRobot(ctx, view, pose, pal, anim.wheelPhase, t.safety?.warning);
  }

  // Rejected target click (invalid or unsafe point), shown briefly.
  if (rejected && now - rejected.at < 1800) {
    const a = 1 - (now - rejected.at) / 1800;
    ctx.save();
    ctx.globalAlpha = a;
    ctx.strokeStyle = pal.danger;
    ctx.lineWidth = 3;
    const rx = X(rejected.x);
    const ry = Y(rejected.y);
    ctx.beginPath();
    ctx.moveTo(rx - 8, ry - 8);
    ctx.lineTo(rx + 8, ry + 8);
    ctx.moveTo(rx + 8, ry - 8);
    ctx.lineTo(rx - 8, ry + 8);
    ctx.stroke();
    ctx.restore();
  }
  ctx.restore();

  // Axis labels (outside the clip).
  ctx.fillStyle = pal.text;
  ctx.font = `${narrow ? 9 : 11}px ui-monospace, Consolas, monospace`;
  const step = view.zoom >= 2 ? 1 : narrow ? 4 : 2;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let x = 0; x <= world.width; x += step) {
    const px = X(x);
    if (px >= m.left - 1 && px <= cssWidth - m.right + 1) ctx.fillText(String(x), px, cssHeight - m.bottom + 5);
  }
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let y = 0; y <= world.height; y += step) {
    const py = Y(y);
    if (py >= m.top - 1 && py <= cssHeight - m.bottom + 1) ctx.fillText(String(y), m.left - 5, py);
  }
}
