import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { SceneAnimator, clampPan, drawScene, makeView, readPalette } from '../simulation/renderer';
import { DisconnectedIcon, SpinnerIcon } from './Icons';
import { MissionStatusBadge } from './StatusBadge';

const EXPLORED_POLL_MS = 2000;
const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const DRAG_THRESHOLD = 5; // px: below this a pointer gesture counts as a click

const LAYERS = [
  ['inflation', 'Safety zones'],
  ['fov', 'Camera view'],
  ['tracks', 'Camera tracks'],
  ['explored', 'Unobserved cells'],
  ['trail', 'Trail'],
];

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

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

const fmtM = (v) => (v === null || v === undefined ? 'Unavailable' : `${v.toFixed(2)} m`);

export function SimulationViewport({
  telemetry,
  world,
  clickMode,
  onMapClick,
  connection,
  online,
  rejected,
  selectedObstacle,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const animRef = useRef(new SceneAnimator());
  const optsRef = useRef({});
  const viewRef = useRef(null);
  const dirtyRef = useRef(true);
  const dragRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [effects, setEffects] = useState(() => !prefersReducedMotion());
  const [layers, setLayers] = useState({ inflation: true, fov: true, tracks: true, explored: false, trail: true });
  const explored = useExploredCells(layers.explored, online);

  // Feed authoritative telemetry to the animator (no React re-render per frame).
  useEffect(() => {
    if (telemetry) {
      animRef.current.ingest(telemetry, performance.now());
      dirtyRef.current = true;
    }
  }, [telemetry]);

  useEffect(() => {
    optsRef.current = { layers, explored, effects, rejected, selectedObstacle };
    dirtyRef.current = true;
  }, [layers, explored, effects, rejected, selectedObstacle]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    optsRef.current.pal = readPalette(el);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Size the canvas and (re)build the view transform when size, zoom or pan change.
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

  // Single animation loop for the lifetime of the component.
  useEffect(() => {
    let raf;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const canvas = canvasRef.current;
      const view = viewRef.current;
      const opts = optsRef.current;
      if (!canvas || !view || !opts.pal) return;
      const now = performance.now();
      const anim = animRef.current;
      // With effects off we only redraw when something changed (or a fade is running).
      const fading = opts.rejected && now - opts.rejected.at < 1800;
      if (!opts.effects && !dirtyRef.current && !fading) return;
      dirtyRef.current = false;
      try {
        const state = anim.frame(now, opts.effects);
        drawScene(canvas.getContext('2d'), view, world, state, { ...opts, now, anim });
      } catch (err) {
        console.error('Viewport render failed', err); // keep the dashboard alive
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
    // Keep the world point under (cx, cy) fixed while zooming.
    const k = next / zoom;
    const nx = cx - view.m.left - (cx - view.m.left - pan.x) * k;
    const ny = cy - view.m.top - (cy - view.m.top - pan.y) * k;
    setZoom(next);
    setPan(next === 1 ? { x: 0, y: 0 } : clampPan({ x: nx, y: ny }, next, view.cssWidth, view.cssHeight, world));
  };
  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

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

  const onPointerDown = (e) => {
    const [px, py] = local(e);
    dragRef.current = { px, py, startPan: pan, moved: false, id: e.pointerId };
    if (zoom > 1) canvasRef.current.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    const [px, py] = local(e);
    setHover(toWorld(px, py));
    const d = dragRef.current;
    if (!d || zoom <= 1) return;
    const dx = px - d.px;
    const dy = py - d.py;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    d.moved = true;
    const view = viewRef.current;
    setPan(clampPan({ x: d.startPan.x + dx, y: d.startPan.y + dy }, zoom, view.cssWidth, view.cssHeight, world));
  };
  const onPointerUp = (e) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d || d.moved) return;
    const p = toWorld(...local(e));
    if (p && telemetry) onMapClick(p);
  };
  const onWheel = (e) => {
    if (!e.ctrlKey && !e.metaKey) return; // plain wheel keeps scrolling the page
    e.preventDefault();
    zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, ...local(e));
  };
  const onKeyDown = (e) => {
    const stepPx = 40;
    const view = viewRef.current;
    const panBy = (dx, dy) => setPan((p) => clampPan({ x: p.x + dx, y: p.y + dy }, zoom, view.cssWidth, view.cssHeight, world));
    const actions = {
      '+': () => zoomAt(1.25),
      '=': () => zoomAt(1.25),
      '-': () => zoomAt(0.8),
      0: resetView,
      ArrowLeft: () => panBy(stepPx, 0),
      ArrowRight: () => panBy(-stepPx, 0),
      ArrowUp: () => panBy(0, stepPx),
      ArrowDown: () => panBy(0, -stepPx),
    };
    if (actions[e.key]) {
      e.preventDefault();
      actions[e.key]();
    }
  };

  // Ctrl+wheel needs a non-passive listener to prevent browser zoom.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  });

  const r = telemetry?.robot;
  const m = telemetry?.mission;
  const status = m?.status;
  const progress = m?.progress;
  const description = telemetry
    ? `Simulation map ${world.width} by ${world.height} metres. Robot at x ${r.x.toFixed(1)}, y ${r.y.toFixed(1)}, heading ${
        r.heading_deg
      } degrees. ${telemetry.target ? `Target at x ${telemetry.target.x}, y ${telemetry.target.y}.` : 'No target selected.'} Mission status ${status}.`
    : 'Simulation map, waiting for telemetry.';

  return (
    <section className="panel viewport" aria-labelledby="viewport-title">
      <div className="panel-head">
        <h2 id="viewport-title">Mission workspace</h2>
        <label className="check">
          <input type="checkbox" checked={effects} onChange={(e) => setEffects(e.target.checked)} />
          Motion effects
        </label>
      </div>
      <p className="muted small viewport-caption">
        Top-down visualisation of the backend simulation state (not a camera feed). Robot pose is smoothed between telemetry
        samples, never extrapolated. Obstacles are simulator ground truth
        {telemetry?.safety?.physics === 'pybullet' ? ', collision-checked in PyBullet.' : '.'}
      </p>

      <div className="viewport-stage" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          role="img"
          tabIndex={0}
          aria-label={`${description} Use plus and minus to zoom, arrow keys to pan, zero to reset the view.`}
          className={`sim-canvas ${clickMode === 'obstacle' ? 'cursor-obstacle' : 'cursor-target'}${zoom > 1 ? ' zoomed' : ''}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => (dragRef.current = null)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKeyDown}
        />

        {telemetry && (
          <div className="hud" aria-hidden="true">
            <MissionStatusBadge status={status} waiting={m.waiting} />
            <div className="hud-progress">
              <span style={{ width: `${(progress ?? 0) * 100}%` }} />
            </div>
            <span className="hud-line mono">
              {progress === null ? 'progress unavailable' : `${Math.round(progress * 100)}% of route`} &middot; to target{' '}
              {fmtM(telemetry.distance_to_target)}
            </span>
            <span className="hud-line mono">t = {telemetry.sim_time.toFixed(1)} s</span>
          </div>
        )}

        <div className="view-controls" role="group" aria-label="Map view">
          <button type="button" onClick={() => zoomAt(1.25)} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={() => zoomAt(0.8)} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out">
            &minus;
          </button>
          <button type="button" onClick={resetView} disabled={zoom === 1} aria-label="Reset view" className="view-reset">
            Fit
          </button>
        </div>

        {!telemetry && (
          <div className="viewport-overlay" role="status">
            {connection === 'closed' ? (
              <>
                <DisconnectedIcon size={22} />
                <strong>Simulation unavailable</strong>
                <span>Waiting for the backend telemetry stream. Retrying automatically.</span>
              </>
            ) : (
              <>
                <SpinnerIcon size={22} />
                <span>Connecting to the simulation...</span>
              </>
            )}
          </div>
        )}
        {telemetry && connection !== 'open' && (
          <div className="viewport-stale" role="status">
            {connection === 'stale' ? 'Telemetry delayed: showing last known state' : 'Reconnecting to the backend...'}
          </div>
        )}
      </div>

      <div className="viewport-foot">
        <p className="hint">
          {clickMode === 'obstacle'
            ? selectedObstacle
              ? `Click a free spot to move ${selectedObstacle}, or click it again to deselect.`
              : 'Click empty floor to place an obstacle, or click an obstacle you added to move it.'
            : 'Click or tap the map to set the target.'}{' '}
          {zoom > 1 ? 'Drag to pan.' : 'Zoom with the buttons or Ctrl + wheel.'}
          <span className="mono pointer-readout" aria-hidden="true">
            {hover ? `  x ${hover.x.toFixed(2)}  y ${hover.y.toFixed(2)} m` : ''}
          </span>
        </p>
        <fieldset className="layer-toggles">
          <legend className="sr-only">Map layers</legend>
          {LAYERS.map(([key, label]) => (
            <label key={key} className="check">
              <input type="checkbox" checked={layers[key]} onChange={() => setLayers((l) => ({ ...l, [key]: !l[key] }))} />
              {label}
            </label>
          ))}
        </fieldset>
        <ul className="legend" aria-label="Map legend">
          <li><span className="sw sw-robot" aria-hidden="true" />Robot, wheels and heading</li>
          <li><span className="sw sw-path" aria-hidden="true" />A* route, active waypoint ringed</li>
          <li><span className="sw sw-ghost" aria-hidden="true" />Previous route (after replan)</li>
          <li><span className="sw sw-target" aria-hidden="true" />Target</li>
          <li><span className="sw sw-static" aria-hidden="true" />Static obstacle</li>
          <li><span className="sw sw-dynamic" aria-hidden="true" />Added obstacle</li>
          <li><span className="sw sw-person" aria-hidden="true" />Person (moving)</li>
          <li><span className="sw sw-alert" aria-hidden="true" />Obstacle that blocked the route</li>
          <li><span className="sw sw-track" aria-hidden="true">&times;</span>Camera-derived track</li>
          <li><span className="sw sw-inflation" aria-hidden="true" />Planner safety zone</li>
          {layers.explored && <li><span className="sw sw-unknown" aria-hidden="true" />Not yet seen by camera</li>}
        </ul>
      </div>
    </section>
  );
}
