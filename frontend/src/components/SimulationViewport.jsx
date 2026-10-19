import { useEffect, useRef, useState } from 'react';
import { Loader2, WifiOff } from 'lucide-react';
import { api } from '../services/api';
import { draw, layout, pointerToWorld, readPalette } from '../simulation/renderer';
import { MissionStatusBadge } from './StatusBadge';

const EXPLORED_POLL_MS = 2000;

const LAYERS = [
  ['inflation', 'Safety zones'],
  ['fov', 'Camera view'],
  ['tracks', 'Camera tracks'],
  ['explored', 'Unobserved cells'],
  ['trail', 'Trail'],
];

/** Polls GET /map for the explored/unknown cell layer while that layer is visible. */
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

export function SimulationViewport({ telemetry, world, clickMode, onMapClick, connection, online }) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const paletteRef = useRef(null);
  const viewRef = useRef(null);
  const trailRef = useRef({ key: null, points: [], simTime: 0 });
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState(null);
  const [layers, setLayers] = useState({ inflation: true, fov: true, tracks: true, explored: false, trail: true });
  const explored = useExploredCells(layers.explored, online);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    paletteRef.current = readPalette(el);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Accumulate the travelled trail; reset on a new mission or a simulation reset.
  if (telemetry?.robot) {
    const key = `${telemetry.scenario}:${telemetry.mission.id}`;
    const tr = trailRef.current;
    const { x, y } = telemetry.robot;
    const last = tr.points[tr.points.length - 1];
    if (tr.key !== key || telemetry.sim_time < tr.simTime) {
      tr.key = key;
      tr.points = [[x, y]];
    } else if (!last || Math.hypot(last[0] - x, last[1] - y) > 0.05) {
      tr.points.push([x, y]);
      if (tr.points.length > 4000) tr.points.shift();
    }
    tr.simTime = telemetry.sim_time;
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !width) return;
    const view = layout(width, world);
    viewRef.current = view;
    const dpr = window.devicePixelRatio || 1;
    canvas.style.height = `${view.cssHeight}px`;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(view.cssHeight * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw(ctx, view, world, telemetry, { trail: trailRef.current.points, layers, pal: paletteRef.current, explored });
  }, [telemetry, world, width, layers, explored]);

  const toWorld = (event) => {
    if (!viewRef.current) return null;
    const rect = canvasRef.current.getBoundingClientRect();
    return pointerToWorld(viewRef.current, world, event.clientX - rect.left, event.clientY - rect.top);
  };

  const r = telemetry?.robot;
  const status = telemetry?.mission?.status;
  const description = telemetry
    ? `Simulation map ${world.width} by ${world.height} metres. Robot at x ${r.x.toFixed(1)}, y ${r.y.toFixed(
        1,
      )}, heading ${r.heading_deg} degrees. ${
        telemetry.target ? `Target at x ${telemetry.target.x}, y ${telemetry.target.y}.` : 'No target selected.'
      } Mission status ${status}. ${telemetry.obstacles.length} obstacles.`
    : 'Simulation map, waiting for telemetry.';

  return (
    <section className="panel viewport" aria-labelledby="viewport-title">
      <div className="panel-head">
        <h2 id="viewport-title">Mission workspace</h2>
        <div className="viewport-meta">
          {telemetry && <MissionStatusBadge status={status} waiting={telemetry.mission.waiting} />}
          {telemetry && (
            <span className="mono muted" title="Simulation clock">
              t = {telemetry.sim_time.toFixed(1)} s
            </span>
          )}
        </div>
      </div>
      <p className="muted small viewport-caption">
        Rendered top-down map of the simulation (not a camera image). Obstacles are ground-truth geometry
        {telemetry?.safety?.physics === 'pybullet' ? ', collision-checked in PyBullet.' : '.'}
      </p>

      <div className="viewport-canvas" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={description}
          className={clickMode === 'obstacle' ? 'cursor-obstacle' : 'cursor-target'}
          onClick={(e) => {
            const p = toWorld(e);
            if (p && telemetry) onMapClick(p);
          }}
          onPointerMove={(e) => setHover(toWorld(e))}
          onPointerLeave={() => setHover(null)}
        />
        {!telemetry && (
          <div className="viewport-overlay" role="status">
            {connection === 'closed' ? (
              <>
                <WifiOff size={22} aria-hidden="true" />
                <strong>Simulation unavailable</strong>
                <span>Waiting for the backend telemetry stream. Retrying automatically.</span>
              </>
            ) : (
              <>
                <Loader2 size={22} className="spin" aria-hidden="true" />
                <span>Connecting to the simulation...</span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="viewport-foot">
        <p className="hint">
          {clickMode === 'obstacle'
            ? 'Click or tap the map to place an obstacle.'
            : 'Click or tap the map to set the target, or enter coordinates in Mission controls.'}
          <span className="mono pointer-readout" aria-hidden="true">
            {hover ? ` x ${hover.x.toFixed(2)}  y ${hover.y.toFixed(2)} m` : ''}
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
          <li><span className="sw sw-robot" aria-hidden="true" />Robot and heading</li>
          <li><span className="sw sw-path" aria-hidden="true" />A* route and waypoints</li>
          <li><span className="sw sw-target" aria-hidden="true" />Target</li>
          <li><span className="sw sw-static" aria-hidden="true" />Static obstacle</li>
          <li><span className="sw sw-dynamic" aria-hidden="true" />Added obstacle</li>
          <li><span className="sw sw-person" aria-hidden="true" />Person (moving)</li>
          <li><span className="sw sw-track" aria-hidden="true">&times;</span>Camera-derived track</li>
          <li><span className="sw sw-inflation" aria-hidden="true" />Planner safety zone</li>
          {layers.explored && <li><span className="sw sw-unknown" aria-hidden="true" />Not yet seen by camera</li>}
        </ul>
      </div>
    </section>
  );
}
