import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { api } from '../services/api';
import { SceneAnimator, clampPan, drawScene, makeView, readPalette } from '../simulation/renderer';

const EXPLORED_POLL_MS = 2000;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const DRAG_THRESHOLD = 5;

function useExploredCells(enabled, online) {
  const [explored, setExplored] = useState(null);
  useEffect(() => {
    if (!enabled || !online) return undefined;
    let cancelled = false;
    const load = () =>
      api
        .map()
        .then((m) => !cancelled && m.grid.cells && setExplored({ resolution: m.grid.resolution, cells: m.grid.cells }))
        .catch(() => {});
    load();
    const id = setInterval(load, EXPLORED_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled, online]);
  return enabled ? explored : null;
}

/** Accurate top-down plan view (also the fallback when WebGL is unavailable). */
export const PlanView2D = forwardRef(function PlanView2D(
  { telemetry, world, onPick, onHover, layers, effects, rejected, selectedObstacle, online, label },
  ref,
) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const animRef = useRef(new SceneAnimator());
  const optsRef = useRef({});
  const viewRef = useRef(null);
  const dirtyRef = useRef(true);
  const dragRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const explored = useExploredCells(layers.explored, online);

  useEffect(() => {
    if (telemetry) {
      animRef.current.ingest(telemetry, performance.now());
      dirtyRef.current = true;
    }
  }, [telemetry]);

  useEffect(() => {
    optsRef.current = { ...optsRef.current, layers, explored, effects, rejected, selectedObstacle };
    dirtyRef.current = true;
  }, [layers, explored, effects, rejected, selectedObstacle]);

  useEffect(() => {
    const el = wrapRef.current;
    optsRef.current.pal = readPalette(el);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !width) return;
    const view = makeView(width, world, zoom, pan);
    viewRef.current = view;
    const dpr = window.devicePixelRatio || 1;
    canvas.style.height = `${view.cssHeight}px`;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(view.cssHeight * dpr);
    canvas.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
    dirtyRef.current = true;
  }, [width, world, zoom, pan]);

  useEffect(() => {
    let raf;
    let last = 0;
    const FRAME_MS = 1000 / 30; // 30 fps cap
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const canvas = canvasRef.current;
      const view = viewRef.current;
      const opts = optsRef.current;
      if (!canvas || !view || !opts.pal) return;
      const now = performance.now();
      if (now - last < FRAME_MS) return;
      const fading = opts.rejected && now - opts.rejected.at < 1800;
      // Redraw only when something changed or is still animating; an idle map costs nothing.
      const animating = opts.effects && animRef.current.animating(now);
      if (!dirtyRef.current && !fading && !animating) return;
      last = now;
      dirtyRef.current = false;
      try {
        const anim = animRef.current;
        drawScene(canvas.getContext('2d'), view, world, anim.frame(now, opts.effects), { ...opts, now, anim });
      } catch (err) {
        console.error('Plan view render failed', err);
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [world]);

  const zoomAt = (factor, px, py) => {
    const view = viewRef.current;
    if (!view) return;
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
    if (next === zoom) return;
    const cx = px ?? view.cssWidth / 2;
    const cy = py ?? view.cssHeight / 2;
    const k = next / zoom;
    const nx = cx - view.m.left - (cx - view.m.left - pan.x) * k;
    const ny = cy - view.m.top - (cy - view.m.top - pan.y) * k;
    setZoom(next);
    setPan(next === 1 ? { x: 0, y: 0 } : clampPan({ x: nx, y: ny }, next, view.cssWidth, view.cssHeight, world));
  };
  const fit = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };
  useImperativeHandle(ref, () => ({ zoomIn: () => zoomAt(1.25), zoomOut: () => zoomAt(0.8), fit, canFit: zoom > 1 }));

  const local = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  };
  const toWorld = (px, py) => {
    const view = viewRef.current;
    if (!view) return null;
    const p = view.toWorld(px, py);
    if (p.x < 0 || p.y < 0 || p.x > world.width || p.y > world.height) return null;
    return { x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100 };
  };
  const hitObstacle = (p) =>
    p &&
    telemetry?.obstacles.find((o) =>
      o.shape === 'circle'
        ? Math.hypot(o.x - p.x, o.y - p.y) <= o.r + 0.15
        : Math.abs(o.x - p.x) <= o.w / 2 + 0.15 && Math.abs(o.y - p.y) <= o.h / 2 + 0.15,
    )?.id;

  useEffect(() => {
    const canvas = canvasRef.current;
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) return; // plain wheel keeps scrolling the page
      e.preventDefault();
      zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, ...local(e));
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  });

  const onKeyDown = (e) => {
    const view = viewRef.current;
    const panBy = (dx, dy) => setPan((p) => clampPan({ x: p.x + dx, y: p.y + dy }, zoom, view.cssWidth, view.cssHeight, world));
    const actions = {
      '+': () => zoomAt(1.25),
      '=': () => zoomAt(1.25),
      '-': () => zoomAt(0.8),
      0: fit,
      ArrowLeft: () => panBy(40, 0),
      ArrowRight: () => panBy(-40, 0),
      ArrowUp: () => panBy(0, 40),
      ArrowDown: () => panBy(0, -40),
    };
    if (actions[e.key]) {
      e.preventDefault();
      actions[e.key]();
    }
  };

  return (
    <div className="plan-view" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        role="img"
        tabIndex={0}
        aria-label={`${label} Plus and minus zoom, arrow keys pan, zero resets the view.`}
        className={`sim-canvas${zoom > 1 ? ' zoomed' : ''}`}
        data-view="plan"
        onPointerDown={(e) => {
          const [px, py] = local(e);
          dragRef.current = { px, py, startPan: pan, moved: false };
          if (zoom > 1) canvasRef.current.setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          const [px, py] = local(e);
          onHover(toWorld(px, py));
          const d = dragRef.current;
          if (!d || zoom <= 1) return;
          const dx = px - d.px;
          const dy = py - d.py;
          if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
          d.moved = true;
          const view = viewRef.current;
          setPan(clampPan({ x: d.startPan.x + dx, y: d.startPan.y + dy }, zoom, view.cssWidth, view.cssHeight, world));
        }}
        onPointerUp={(e) => {
          const d = dragRef.current;
          dragRef.current = null;
          if (!d || d.moved) return;
          const p = toWorld(...local(e));
          onPick({ point: p, obstacleId: hitObstacle(p) ?? null });
        }}
        onPointerCancel={() => (dragRef.current = null)}
        onPointerLeave={() => onHover(null)}
        onKeyDown={onKeyDown}
      />
    </div>
  );
});
