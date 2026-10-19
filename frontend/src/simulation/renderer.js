// Canvas renderer for the top-down simulation map. Pure drawing code: it reads
// telemetry and never changes state. World frame: metres, origin bottom-left, +y up.

export const FOV_DEG = 70;
const CAMERA_RANGE = 4; // metres drawn for the field-of-view cone (display only)

export function readPalette(el) {
  const s = getComputedStyle(el);
  const v = (name) => s.getPropertyValue(name).trim();
  return {
    floor: v('--map-floor'),
    grid: v('--map-grid'),
    unknown: v('--map-unknown'),
    static: v('--map-static'),
    staticEdge: v('--map-static-edge'),
    dynamic: v('--map-dynamic'),
    dynamicEdge: v('--map-dynamic-edge'),
    person: v('--map-person'),
    inflation: v('--map-inflation'),
    path: v('--map-path'),
    trail: v('--map-trail'),
    robot: v('--map-robot'),
    track: v('--map-track'),
    text: v('--color-text-muted'),
    danger: v('--color-danger'),
    accentSoft: v('--color-accent-soft'),
  };
}

/** Canvas layout for a given CSS width. Shared with pointer -> world conversion. */
export function layout(cssWidth, world) {
  const narrow = cssWidth < 520;
  const m = { left: narrow ? 20 : 28, right: 8, top: 8, bottom: narrow ? 18 : 22 };
  const scale = (cssWidth - m.left - m.right) / world.width;
  const cssHeight = Math.round(world.height * scale + m.top + m.bottom);
  return { m, scale, cssHeight, narrow };
}

/** Convert a pointer position (relative to the canvas) to world metres, or null if off-map. */
export function pointerToWorld(view, world, px, py) {
  const x = (px - view.m.left) / view.scale;
  const y = world.height - (py - view.m.top) / view.scale;
  if (x < 0 || y < 0 || x > world.width || y > world.height) return null;
  return { x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100 };
}

function polyline(ctx, pts, X, Y) {
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
}

export function draw(ctx, view, world, t, { trail, layers, pal, explored }) {
  const { m, scale, narrow } = view;
  const X = (x) => m.left + x * scale;
  const Y = (y) => m.top + (world.height - y) * scale;
  const W = world.width * scale;
  const H = world.height * scale;

  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  ctx.fillStyle = pal.floor;
  ctx.fillRect(m.left, m.top, W, H);

  // Cells the camera has never observed (perception view, from GET /map).
  if (layers.explored && explored) {
    const res = explored.resolution;
    ctx.fillStyle = pal.unknown;
    explored.cells.forEach((row, r) => {
      for (let c = 0; c < row.length; c += 1) {
        if (row[c] === '?') ctx.fillRect(X(c * res), Y((r + 1) * res), res * scale + 0.5, res * scale + 0.5);
      }
    });
  }

  // 1 m grid and axis labels.
  ctx.lineWidth = 1;
  ctx.strokeStyle = pal.grid;
  ctx.beginPath();
  for (let x = 1; x < world.width; x += 1) {
    ctx.moveTo(Math.round(X(x)) + 0.5, m.top);
    ctx.lineTo(Math.round(X(x)) + 0.5, m.top + H);
  }
  for (let y = 1; y < world.height; y += 1) {
    ctx.moveTo(m.left, Math.round(Y(y)) + 0.5);
    ctx.lineTo(m.left + W, Math.round(Y(y)) + 0.5);
  }
  ctx.stroke();
  ctx.fillStyle = pal.text;
  ctx.font = `${narrow ? 9 : 11}px ui-monospace, Consolas, monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let x = 0; x <= world.width; x += narrow ? 4 : 2) ctx.fillText(String(x), X(x), m.top + H + 4);
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let y = 0; y <= world.height; y += narrow ? 4 : 2) ctx.fillText(String(y), m.left - 5, Y(y));
  ctx.strokeStyle = pal.staticEdge;
  ctx.strokeRect(m.left + 0.5, m.top + 0.5, W - 1, H - 1);

  if (!t) return;
  const obstacles = t.obstacles || [];
  const inflation = t.safety?.inflation ?? 0.45;

  // Inflated safety zones used by the planner (dashed outline).
  if (layers.inflation) {
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = pal.inflation;
    for (const o of obstacles) {
      ctx.beginPath();
      if (o.shape === 'circle') {
        ctx.arc(X(o.x), Y(o.y), (o.r + inflation) * scale, 0, Math.PI * 2);
      } else {
        const r = inflation * scale;
        ctx.roundRect(X(o.x - o.w / 2) - r, Y(o.y + o.h / 2) - r, o.w * scale + 2 * r, o.h * scale + 2 * r, r);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  // Obstacles (ground truth from the simulator).
  for (const o of obstacles) {
    const isPerson = o.label === 'person';
    ctx.fillStyle = isPerson ? pal.person : o.dynamic ? pal.dynamic : pal.static;
    ctx.strokeStyle = isPerson ? pal.person : o.dynamic ? pal.dynamicEdge : pal.staticEdge;
    ctx.lineWidth = o.dynamic ? 2 : 1;
    ctx.beginPath();
    if (o.shape === 'circle') ctx.arc(X(o.x), Y(o.y), o.r * scale, 0, Math.PI * 2);
    else ctx.rect(X(o.x - o.w / 2), Y(o.y + o.h / 2), o.w * scale, o.h * scale);
    ctx.fill();
    ctx.stroke();
    if (!narrow && (o.dynamic || isPerson)) {
      ctx.fillStyle = pal.robot;
      ctx.font = '11px -apple-system, "Segoe UI", sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'bottom';
      const top = o.shape === 'circle' ? o.y + o.r : o.y + o.h / 2;
      ctx.fillText(o.id, X(o.x) + 6, Y(top) - 2);
    }
  }

  // Camera-derived obstacle tracks (perception estimate, not used for safety).
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

  const r = t.robot;
  // Camera field of view.
  if (layers.fov && r) {
    const half = ((FOV_DEG / 2) * Math.PI) / 180;
    ctx.fillStyle = pal.accentSoft;
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    ctx.moveTo(X(r.x), Y(r.y));
    ctx.arc(X(r.x), Y(r.y), CAMERA_RANGE * scale, -r.theta - half, -r.theta + half);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  // Travelled trail.
  if (layers.trail && trail.length > 1) {
    ctx.strokeStyle = pal.trail;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([2, 3]);
    polyline(ctx, trail, X, Y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Planned A* route + waypoints.
  const path = t.path || [];
  if (path.length > 1) {
    ctx.strokeStyle = pal.path;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    polyline(ctx, path, X, Y);
    ctx.stroke();
    const current = t.current_waypoint?.index;
    path.forEach(([x, y], i) => {
      if (i === 0) return;
      ctx.beginPath();
      ctx.arc(X(x), Y(y), i === current ? 5 : 3.5, 0, Math.PI * 2);
      ctx.fillStyle = i === current ? pal.path : pal.floor;
      ctx.fill();
      ctx.strokeStyle = pal.path;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
  }

  // Target.
  if (t.target) {
    const tx = X(t.target.x);
    const ty = Y(t.target.y);
    ctx.strokeStyle = pal.robot;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(tx, ty, Math.max(0.2 * scale, 6), 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tx - 10, ty);
    ctx.lineTo(tx + 10, ty);
    ctx.moveTo(tx, ty - 10);
    ctx.lineTo(tx, ty + 10);
    ctx.stroke();
    if (t.mission?.status === 'goal_reached') {
      ctx.fillStyle = pal.path;
      ctx.beginPath();
      ctx.arc(tx, ty, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Robot: footprint and heading.
  if (r) {
    const cx = X(r.x);
    const cy = Y(r.y);
    const rad = Math.max(r.radius * scale, 5);
    if (t.safety?.warning) {
      ctx.strokeStyle = pal.danger;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, cy, rad + 5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = pal.robot;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, rad, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(-r.theta) * rad * 1.6, cy + Math.sin(-r.theta) * rad * 1.6);
    ctx.stroke();
    ctx.fillStyle = pal.robot;
    ctx.beginPath();
    ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }
}
