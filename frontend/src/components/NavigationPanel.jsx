import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { Term } from './Term';

const POLL_MS = 1500;
const COLORS = {
  '#': '#4a4f55', // occupied (obstacle footprint)
  '+': '#e8b7b0', // inflated: unsafe for the robot centre
  '?': '#d9d6cf', // free but never seen by the camera
  '.': '#f7f6f2', // free and observed
};

/** Polls GET /map: the planner's actual occupancy grid (not a drawing of the scene). */
function useGrid(online) {
  const [grid, setGrid] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (!online) return undefined;
    let cancelled = false;
    const load = () =>
      api
        .map()
        .then((m) => {
          if (cancelled) return;
          setGrid(m.grid);
          setError(null);
        })
        .catch((e) => !cancelled && setError(e.message));
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [online]);
  return { grid, error };
}

function GridCanvas({ grid, telemetry }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !grid?.cells) return;
    const cell = 4;
    const rows = grid.cells.length;
    const cols = grid.cells[0].length;
    canvas.width = cols * cell;
    canvas.height = rows * cell;
    const ctx = canvas.getContext('2d');
    for (let r = 0; r < rows; r += 1) {
      const row = grid.cells[r];
      const lidar = grid.lidar_occupied?.[r];
      for (let c = 0; c < cols; c += 1) {
        ctx.fillStyle = lidar && lidar[c] === '1' ? '#e0782f' : COLORS[row[c]] || '#fff';
        // Row 0 is y = 0 (bottom of the map), so flip vertically.
        ctx.fillRect(c * cell, (rows - 1 - r) * cell, cell, cell);
      }
    }
    if (!telemetry) return;
    const res = grid.resolution;
    const X = (x) => (x / res) * cell;
    const Y = (y) => canvas.height - (y / res) * cell;
    const path = telemetry.path || [];
    if (path.length > 1) {
      ctx.strokeStyle = '#0f6e6a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      path.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.stroke();
    }
    if (telemetry.target) {
      ctx.strokeStyle = '#b07d00';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(X(telemetry.target.x), Y(telemetry.target.y), 5, 0, Math.PI * 2);
      ctx.stroke();
    }
    const r = telemetry.robot;
    ctx.fillStyle = '#1b1d1f';
    ctx.beginPath();
    ctx.arc(X(r.x), Y(r.y), 4, 0, Math.PI * 2);
    ctx.fill();
  }, [grid, telemetry]);

  return (
    <canvas
      ref={ref}
      className="grid-canvas"
      role="img"
      aria-label={`Occupancy grid, ${grid?.cols ?? 0} by ${grid?.rows ?? 0} cells of ${grid?.resolution ?? 0} m, with the current route.`}
    />
  );
}

const OUTCOME = { replanned: 'Replanned', blocked: 'No route' };
const CAUSE = { obstruction: 'Route obstructed', proximity: 'Proximity stop', retry: 'Retry after wait', safety_stop: 'Safety stop' };

export function NavigationPanel({ telemetry, online }) {
  const { grid, error } = useGrid(online);
  const plan = telemetry?.last_plan;
  const history = telemetry?.replan_history ?? [];
  const status = telemetry?.mission?.status;

  let validity = 'No route';
  let tone = 'pending';
  if (status === 'replanning') {
    validity = 'Invalidated: replanning';
    tone = 'degraded';
  } else if (plan && !plan.success) {
    validity = `No valid route (${plan.reason.replace('_', ' ')})`;
    tone = 'down';
  } else if (plan?.success && telemetry.path.length > 1) {
    validity = `Valid: ${plan.checked_samples} samples clear of inflated cells`;
    tone = 'ok';
  }

  return (
    <section className="panel" id="navigation" aria-labelledby="navigation-title">
      <div className="panel-head">
        <h2 id="navigation-title">Navigation</h2>
        {grid && (
          <span className="muted small mono">
            {grid.cols}&times;{grid.rows} cells, {grid.resolution} m
          </span>
        )}
      </div>

      {error && <p className="feedback-msg feedback-error">Occupancy grid unavailable: {error}</p>}
      {grid ? (
        <figure className="grid-figure">
          <GridCanvas grid={grid} telemetry={telemetry} />
          <figcaption>
            <ul className="legend" aria-label="Occupancy grid legend">
              <li><span className="sw" style={{ background: COLORS['#'] }} aria-hidden="true" />Occupied</li>
              <li><span className="sw" style={{ background: COLORS['+'] }} aria-hidden="true" />Inflated (radius + margin)</li>
              <li><span className="sw" style={{ background: COLORS['.'], border: '1px solid #ccc' }} aria-hidden="true" />Free, seen by camera</li>
              <li><span className="sw" style={{ background: COLORS['?'] }} aria-hidden="true" />Free, not yet seen</li>
              <li><span className="sw" style={{ background: '#e0782f' }} aria-hidden="true" />LiDAR return (last 2 s)</li>
              <li><span className="sw sw-path" aria-hidden="true" />A* route</li>
            </ul>
          </figcaption>
        </figure>
      ) : (
        !error && <p className="empty">{online ? 'Loading the occupancy grid...' : 'Backend offline: grid unavailable.'}</p>
      )}

      <dl className="kv-grid">
        <div className={`kv kv-${tone === 'ok' ? 'success' : tone === 'down' ? 'danger' : tone === 'degraded' ? 'warning' : ''}`}>
          <dt>
            <Term tip="Each new A* route is re-checked point by point against the live occupancy grid before the robot is allowed to drive it.">
              Route validity
            </Term>
          </dt>
          <dd>{validity}</dd>
        </div>
      </dl>

      <h3 className="sub">Replanning history ({history.length})</h3>
      {history.length ? (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Cause</th>
                <th scope="col">Outcome</th>
                <th scope="col">Route</th>
              </tr>
            </thead>
            <tbody>
              {[...history].reverse().map((h, i) => (
                <tr key={`${h.sim_time}-${i}`}>
                  <td className="mono">{h.sim_time.toFixed(1)} s</td>
                  <td>
                    {CAUSE[h.cause] || h.cause}
                    {h.obstacle ? <span className="muted"> ({h.obstacle})</span> : null}
                  </td>
                  <td>{OUTCOME[h.outcome] || h.outcome}</td>
                  <td className="mono small">
                    {h.previous_length !== null ? `${h.previous_length.toFixed(1)}` : '—'} &rarr;{' '}
                    {h.new_length !== null ? `${h.new_length.toFixed(1)} m` : 'none'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="empty">No replans yet. Drop an obstacle on the route during a mission to trigger one.</p>
      )}
    </section>
  );
}
