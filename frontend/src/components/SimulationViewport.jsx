import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { CrosshairIcon, ObstacleIcon, SpinnerIcon, DisconnectedIcon } from './Icons';
import { PlanView2D } from './PlanView2D';
import { MissionStatusBadge } from './StatusBadge';

const Viewport3D = lazy(() => import('./Viewport3D'));

const LAYERS = [
  ['route', 'Route'],
  ['inflation', 'Safety zones'],
  ['sensor', 'Camera overlay'],
  ['trail', 'Trail'],
  ['explored', 'Unobserved cells', 'plan'],
];

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function readStored(key, fallback) {
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function store(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: preference simply is not remembered */
  }
}

const fmtM = (v) => (v === null || v === undefined ? 'unavailable' : `${v.toFixed(2)} m`);

function Segmented({ label, value, options, onChange, disabled }) {
  return (
    <div className="tool-group" role="group" aria-label={label}>
      {options.map(([v, text, Icon]) => (
        <button
          key={v}
          type="button"
          className={`tool-btn${value === v ? ' on' : ''}`}
          aria-pressed={value === v}
          disabled={disabled}
          onClick={() => onChange(v)}
        >
          {Icon && <Icon size={14} />}
          {text}
        </button>
      ))}
    </div>
  );
}

export function SimulationViewport({
  telemetry,
  world,
  clickMode,
  setClickMode,
  onMapClick,
  connection,
  online,
  rejected,
  selectedObstacle,
}) {
  const viewRef = useRef(null);
  const [view, setView] = useState(() => readStored('vistara.view', '3d'));
  const [camera, setCamera] = useState('orbit');
  const [webglFailed, setWebglFailed] = useState(false);
  const [hover, setHover] = useState(null);
  const [effects, setEffects] = useState(() => !prefersReducedMotion());
  const [layers, setLayers] = useState({ route: true, inflation: true, sensor: true, trail: true, explored: false });
  const activeView = webglFailed ? 'plan' : view;

  useEffect(() => store('vistara.view', view), [view]);

  const m = telemetry?.mission;
  const status = m?.status;
  const progress = m?.progress;
  const r = telemetry?.robot;
  const label = telemetry
    ? `Simulation of a ${world.width} by ${world.height} metre warehouse. Robot at x ${r.x.toFixed(1)}, y ${r.y.toFixed(
        1,
      )}, heading ${r.heading_deg} degrees. ${
        telemetry.target ? `Target at x ${telemetry.target.x}, y ${telemetry.target.y}.` : 'No target selected.'
      } Mission status ${status}.`
    : 'Simulation view, waiting for telemetry.';

  const onPick = (pick) => {
    if (telemetry && (pick.point || pick.obstacleId)) onMapClick(pick);
  };

  const viewProps = {
    telemetry,
    world,
    onPick,
    onHover: setHover,
    layers,
    effects,
    rejected,
    selectedObstacle,
    online,
    label,
  };

  const physics = telemetry?.safety?.physics;
  const p = telemetry?.perception;
  const conn = { open: 'Live', stale: 'Delayed', connecting: 'Connecting', closed: 'Offline' }[connection];

  return (
    <section className="panel viewport" aria-labelledby="viewport-title">
      <div className="panel-head">
        <h2 id="viewport-title">Mission workspace</h2>
        <ul className="chips-row" aria-label="Simulation mode">
          <li className={`chip chip-${connection === 'open' ? 'ok' : connection === 'closed' ? 'down' : 'warn'}`}>
            <span className="chip-dot" aria-hidden="true" />
            Telemetry: {conn}
          </li>
          {physics && <li className="chip">Physics: {physics === 'pybullet' ? 'PyBullet' : 'analytic 2D'}</li>}
          {p && <li className="chip">Detector: {p.mode === 'yolov8' ? 'YOLOv8' : 'simulated (ground truth)'}</li>}
        </ul>
      </div>

      <div className="toolbar" role="toolbar" aria-label="Viewport tools">
        <Segmented
          label="View"
          value={activeView}
          onChange={setView}
          options={[
            ['3d', '3D'],
            ['plan', 'Plan'],
          ]}
          disabled={webglFailed}
        />
        {activeView === '3d' && (
          <Segmented
            label="Camera"
            value={camera}
            onChange={setCamera}
            options={[
              ['orbit', 'Orbit'],
              ['top', 'Top'],
              ['follow', 'Follow robot'],
            ]}
          />
        )}
        <div className="tool-group" role="group" aria-label="Zoom">
          <button type="button" className="tool-btn" onClick={() => viewRef.current?.zoomOut()} aria-label="Zoom out">
            &minus;
          </button>
          <button type="button" className="tool-btn" onClick={() => viewRef.current?.zoomIn()} aria-label="Zoom in">
            +
          </button>
          <button type="button" className="tool-btn" onClick={() => viewRef.current?.fit()} aria-label="Reset view">
            Fit
          </button>
        </div>
        <Segmented
          label="Click action"
          value={clickMode}
          onChange={setClickMode}
          options={[
            ['target', 'Select destination', CrosshairIcon],
            ['obstacle', 'Add obstacle', ObstacleIcon],
          ]}
        />
      </div>

      <div className="toolbar toolbar-sub" role="group" aria-label="Overlays">
        {LAYERS.filter(([, , only]) => !only || only === activeView).map(([key, text]) => (
          <label key={key} className="check">
            <input type="checkbox" checked={layers[key]} onChange={() => setLayers((l) => ({ ...l, [key]: !l[key] }))} />
            {text}
          </label>
        ))}
        <label className="check check-sep">
          <input type="checkbox" checked={effects} onChange={(e) => setEffects(e.target.checked)} />
          Motion effects
        </label>
      </div>

      <div className={`viewport-stage stage-${activeView}`}>
        {activeView === '3d' ? (
          <Suspense
            fallback={
              <div className="viewport-overlay" role="status">
                <SpinnerIcon size={22} />
                <span>Loading 3D view...</span>
              </div>
            }
          >
            <Viewport3D ref={viewRef} {...viewProps} camera={camera} onError={() => setWebglFailed(true)} />
          </Suspense>
        ) : (
          <PlanView2D ref={viewRef} {...viewProps} />
        )}

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
            <span className="hud-line mono">
              t = {telemetry.sim_time.toFixed(1)} s &middot; replans {m.replans}
            </span>
          </div>
        )}
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
          {webglFailed && <strong>3D view unavailable on this device (WebGL); showing the plan view. </strong>}
          {clickMode === 'obstacle'
            ? selectedObstacle
              ? `Click a free spot to move ${selectedObstacle}, or click it again to deselect.`
              : 'Click empty floor to add an obstacle, or click an obstacle you added to select and move it.'
            : 'Click or tap the floor to select the destination.'}{' '}
          {activeView === '3d'
            ? 'Drag to orbit, right-drag or two fingers to pan, Ctrl + wheel or pinch to zoom.'
            : 'Zoom with the buttons or Ctrl + wheel; drag to pan when zoomed.'}
          <span className="mono pointer-readout" aria-hidden="true">
            {hover ? `  x ${hover.x.toFixed(2)}  y ${hover.y.toFixed(2)} m` : ''}
          </span>
        </p>
        <p className="muted small">
          {activeView === '3d' ? '3D rendering' : 'Top-down rendering'} of the backend simulation state, not a camera feed.
          Robot pose is smoothed between telemetry samples and never extrapolated. Obstacle models are drawn at their simulated
          footprint and height; racking, cartons and the robot body are visual detail.
        </p>
        <ul className="legend" aria-label="Legend">
          <li><span className="sw sw-robot" aria-hidden="true" />Robot (0.3 m radius, camera at 0.5 m)</li>
          <li><span className="sw sw-path" aria-hidden="true" />A* route, active waypoint ringed</li>
          <li><span className="sw sw-ghost" aria-hidden="true" />Previous route after a replan</li>
          <li><span className="sw sw-target" aria-hidden="true" />Destination</li>
          <li><span className="sw sw-static" aria-hidden="true" />Static obstacle</li>
          <li><span className="sw sw-dynamic" aria-hidden="true" />Added obstacle</li>
          <li><span className="sw sw-person" aria-hidden="true" />Person (moving)</li>
          <li><span className="sw sw-alert" aria-hidden="true" />Obstacle that blocked the route</li>
          <li><span className="sw sw-inflation" aria-hidden="true" />Planner safety zone (radius + margin)</li>
          <li><span className="sw sw-fov" aria-hidden="true" />Camera field of view (simulated camera, {p?.camera ? `${p.camera.fov_deg}°, ${p.camera.range} m` : '70°'})</li>
          <li><span className="sw sw-detect" aria-hidden="true" />In view of the simulated detector</li>
          <li><span className="sw sw-track" aria-hidden="true">&times;</span>Camera-derived track</li>
        </ul>
      </div>
    </section>
  );
}
