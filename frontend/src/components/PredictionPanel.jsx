import { api } from '../services/api';
import { CheckIcon, InfoIcon, WarningIcon } from './Icons';
import { Term } from './Term';

const RISK = {
  LOW: ['ok', 'LOW', CheckIcon],
  MEDIUM: ['warn', 'MEDIUM', WarningIcon],
  HIGH: ['bad', 'HIGH', WarningIcon],
};
const ACTION = {
  continue: 'Normal speed',
  slow: 'Slowing down',
  crawl: 'Crawling',
  wait: 'Waiting for the obstacle to pass',
  stop: 'Stopped, replanning around the predicted path',
  evade: 'Stepping aside',
  monitor_only: 'Monitoring only (reactive baseline)',
};
const STATE = { confirmed: 'Tracked', coasting: 'Uncertain (not seen)', tentative: 'New' };
const HORIZON = 3; // seconds: the prediction horizon used by the backend risk assessment
const RADAR_SPAN = 10; // metres shown across the conflict radar

const fmt = (v, d = 2, unit = '') => (v === null || v === undefined ? '—' : `${Number(v).toFixed(d)}${unit}`);

/**
 * One-line state of the predictive layer, derived only from backend fields
 * (mission status, prediction action, risk and speed factor).
 */
export function predictiveHeadline(telemetry) {
  const p = telemetry?.prediction;
  const m = telemetry?.mission;
  if (!p || !m) return null;
  const pct = Math.round((p.speed_factor ?? 1) * 100);
  if (m.status === 'blocked' && m.waiting) return ['warn', 'Passage blocked', 'Waiting for moving obstacles to clear'];
  if (m.status === 'blocked') return ['bad', 'No safe route', 'Robot stopped safely'];
  if (m.status === 'replanning') return ['warn', 'Route invalidated', 'Replanning a safe route'];
  if (m.status === 'goal_reached') return ['ok', 'Destination reached', 'Mission complete'];
  if (m.status !== 'navigating') return ['idle', 'Standby', p.reason || 'No active route'];
  if (!p.enabled) {
    return p.risk === 'LOW'
      ? ['idle', 'Reactive baseline', 'Predictions shown but not acted on']
      : ['warn', `Risk ${p.risk} (not acted on)`, 'Reactive baseline: speed is not adjusted for predictions'];
  }
  switch (p.action) {
    case 'slow':
    case 'crawl':
      return ['warn', 'Conflict predicted', `Reducing speed to ${pct}%`];
    case 'wait':
      return ['warn', 'Conflict predicted', 'Waiting for the object to pass'];
    case 'stop':
      return ['bad', 'Route invalidated', 'Stopped; replanning around the predicted path'];
    case 'evade':
      return ['bad', 'Object heading for robot', 'Stepping aside'];
    default:
      return p.risk === 'LOW'
        ? ['ok', 'Path clear', 'Continuing at planned speed']
        : ['warn', `Risk ${p.risk}`, pct < 100 ? `Speed limited to ${pct}%` : 'Monitoring; no conflict at planned speed'];
  }
}

function RiskMeter({ risk }) {
  return (
    <div className="risk-meter" role="img" aria-label={`Risk level ${risk}`}>
      {['LOW', 'MEDIUM', 'HIGH'].map((level) => (
        <span key={level} className={`rm-seg rm-${level.toLowerCase()}${level === risk ? ' on' : ''}`}>
          {level}
        </span>
      ))}
    </div>
  );
}

/** 0-3 s horizon: HIGH zone (< 1.5 s), MEDIUM zone (< 3 s) and the predicted conflict, if any. */
function HorizonBar({ ttc }) {
  const pos = ttc == null ? null : Math.min(ttc, HORIZON) / HORIZON;
  return (
    <div className="horizon" aria-label={ttc == null ? 'No conflict predicted within 3 s' : `Conflict predicted in ${ttc.toFixed(1)} s`}>
      <div className="hz-track">
        <span className="hz-zone hz-high" style={{ width: '50%' }} />
        <span className="hz-zone hz-med" style={{ width: '50%' }} />
        {pos !== null && <span className="hz-marker" style={{ left: `${pos * 100}%` }} />}
      </div>
      <div className="hz-ticks mono" aria-hidden="true">
        {[0, 0.5, 1, 1.5, 2, 2.5, 3].map((t) => (
          <span key={t} style={{ left: `${(t / HORIZON) * 100}%` }}>
            {t}s
          </span>
        ))}
      </div>
    </div>
  );
}

/** Clip a polyline (SVG coordinates) to the square [0, span] (Liang-Barsky per segment). */
function clipPolyline(points, span) {
  const out = [];
  const clipSeg = ([x0, y0], [x1, y1]) => {
    let t0 = 0;
    let t1 = 1;
    const dx = x1 - x0;
    const dy = y1 - y0;
    for (const [pp, q] of [[-dx, x0], [dx, span - x0], [-dy, y0], [dy, span - y0]]) {
      if (pp === 0) {
        if (q < 0) return null;
      } else {
        const r = q / pp;
        if (pp < 0) t0 = Math.max(t0, r);
        else t1 = Math.min(t1, r);
      }
    }
    return t0 > t1 ? null : [[x0 + t0 * dx, y0 + t0 * dy], [x0 + t1 * dx, y0 + t1 * dy]];
  };
  for (let i = 1; i < points.length; i += 1) {
    const seg = clipSeg(points[i - 1], points[i]);
    if (seg) out.push(seg);
  }
  return out.map(([a, b]) => `M${a[0].toFixed(2)},${a[1].toFixed(2)}L${b[0].toFixed(2)},${b[1].toFixed(2)}`).join('');
}

/** Robot-centred top-down view of the route ahead, tracked objects and their predictions. */
function ConflictRadar({ telemetry, focus }) {
  const r = telemetry.robot;
  const p = telemetry.prediction;
  const half = RADAR_SPAN / 2;
  // World -> SVG: x right, y up (flip), robot at the centre.
  const sx = (x) => x - r.x + half;
  const sy = (y) => half - (y - r.y);
  const wp = telemetry.current_waypoint?.index ?? 0;
  const ahead = (telemetry.path || []).slice(Math.max(0, wp - 1));
  // Geometry is clipped to the window so nothing in the SVG extends past the radar.
  const route = clipPolyline([[r.x, r.y], ...ahead].map(([x, y]) => [sx(x), sy(y)]), RADAR_SPAN);
  const inside = (x, y, pad = 0) => x >= pad && x <= RADAR_SPAN - pad && y >= pad && y <= RADAR_SPAN - pad;
  const heading = r.theta ?? ((r.heading_deg ?? 0) * Math.PI) / 180;
  const tip = [Math.cos(heading) * 0.55, Math.sin(heading) * 0.55];
  const left = [Math.cos(heading + 2.5) * 0.35, Math.sin(heading + 2.5) * 0.35];
  const right = [Math.cos(heading - 2.5) * 0.35, Math.sin(heading - 2.5) * 0.35];
  const tri = [tip, left, right].map(([dx, dy]) => `${(half + dx).toFixed(2)},${(half - dy).toFixed(2)}`).join(' ');
  const target = telemetry.target;
  return (
    <svg className="radar" viewBox={`0 0 ${RADAR_SPAN} ${RADAR_SPAN}`} role="img" aria-label="Conflict radar: robot-centred view of the route ahead, tracked objects and their predicted positions over 3 seconds">
      <defs>
        <clipPath id="radar-clip">
          <rect x="0" y="0" width={RADAR_SPAN} height={RADAR_SPAN} />
        </clipPath>
      </defs>
      <g clipPath="url(#radar-clip)">
        {[1, 2, 3, 4].map((m) => (
          <circle key={m} cx={half} cy={half} r={m} className="rd-ring" />
        ))}
        <line x1={half} y1="0" x2={half} y2={RADAR_SPAN} className="rd-axis" />
        <line x1="0" y1={half} x2={RADAR_SPAN} y2={half} className="rd-axis" />
        {route && <path d={route} className="rd-route" />}
        {target && inside(sx(target.x), sy(target.y), 0.3) && <circle cx={sx(target.x)} cy={sy(target.y)} r="0.22" className="rd-target" />}
        {p.tracks.filter((t) => inside(sx(t.x), sy(t.y), 0.8)).map((t) => {
          const risk = (t.risk || 'LOW').toLowerCase();
          const isFocus = focus && t.id === focus.id;
          return (
            <g key={t.id} className={`rd-track rd-${risk}${t.state !== 'confirmed' ? ' rd-uncertain' : ''}${isFocus ? ' rd-focus' : ''}`}>
              {t.moving && t.predicted.length > 0 && (
                <path className="rd-predline" d={clipPolyline([[t.x, t.y], ...t.predicted.map((q) => [q.x, q.y])].map(([x, y]) => [sx(x), sy(y)]), RADAR_SPAN)} />
              )}
              {t.moving &&
                t.predicted.filter((q) => inside(sx(q.x), sy(q.y), Math.max(q.sigma, 0.05) + (t.radius || 0.3))).map((q) => (
                  <g key={q.t}>
                    <circle cx={sx(q.x)} cy={sy(q.y)} r={Math.max(q.sigma, 0.05) + (t.radius || 0.3)} className="rd-sigma" />
                    <circle cx={sx(q.x)} cy={sy(q.y)} r="0.07" className="rd-pdot" />
                  </g>
                ))}
              <circle cx={sx(t.x)} cy={sy(t.y)} r={t.radius || 0.3} className="rd-obj" />
              <text x={sx(t.x) + (t.radius || 0.3) + 0.12} y={sy(t.y) + 0.12} className="rd-label">
                T{t.id}
              </text>
            </g>
          );
        })}
        {p.conflicts.filter((c) => inside(sx(c.x), sy(c.y), 0.3)).map((c, i) => (
          <g key={i} className="rd-conflict" transform={`translate(${sx(c.x)} ${sy(c.y)})`}>
            <line x1="-0.22" y1="-0.22" x2="0.22" y2="0.22" />
            <line x1="-0.22" y1="0.22" x2="0.22" y2="-0.22" />
          </g>
        ))}
        <circle cx={half} cy={half} r={r.radius || 0.3} className="rd-robot-body" />
        <polygon points={tri} className="rd-robot" />
      </g>
      <text x="0.2" y={RADAR_SPAN - 0.25} className="rd-scale">
        rings 1 m
      </text>
    </svg>
  );
}

/**
 * OBSERVE -> TRACK -> PREDICT -> ASSESS -> DECIDE -> ACT, each stage lit only by live state:
 * "on" when it is processing something, "alert" when it changed the robot's behaviour.
 */
function Pipeline({ telemetry }) {
  const p = telemetry.prediction;
  const m = telemetry.mission;
  const navigating = m.status === 'navigating' || m.status === 'replanning';
  const confirmed = p.tracks.filter((t) => t.state === 'confirmed');
  const moving = confirmed.filter((t) => t.moving);
  const acting = p.enabled && (p.action !== 'continue' || p.speed_factor < 1);
  const stages = [
    ['Observe', p.measurements > 0 ? 'on' : 'off', `${p.measurements} object${p.measurements === 1 ? '' : 's'} in scan`],
    ['Track', confirmed.length ? 'on' : 'off', `${confirmed.length} confirmed`],
    ['Predict', moving.length ? 'on' : 'off', moving.length ? `${moving.length} moving, 0.5-3 s` : 'nothing moving'],
    ['Assess', p.risk !== 'LOW' ? 'alert' : navigating && moving.length ? 'on' : 'off', `risk ${p.risk}`],
    ['Decide', acting ? 'alert' : navigating ? 'on' : 'off', p.enabled ? p.action.replace('_', ' ') : 'baseline: no action'],
    [
      'Act',
      acting || m.status === 'replanning' || m.waiting ? 'alert' : navigating ? 'on' : 'off',
      m.status === 'replanning' ? 'replanning' : m.waiting ? 'waiting' : navigating ? `${Math.round((p.speed_factor ?? 1) * 100)}% speed` : 'robot idle',
    ],
  ];
  return (
    <ol className="predict-pipeline" aria-label="Predictive navigation pipeline, live">
      {stages.map(([name, state, detail]) => (
        <li key={name} className={`pl-stage pl-${state}`}>
          <span className="pl-name">{name}</span>
          <span className="pl-detail mono">{detail}</span>
          <span className="sr-only">{state === 'alert' ? '(changing behaviour)' : state === 'on' ? '(active)' : '(idle)'}</span>
        </li>
      ))}
    </ol>
  );
}

/** Predictive Intelligence: tracked objects, predictions, risk and the robot's response. */
export function PredictionPanel({ telemetry, online, command }) {
  const p = telemetry?.prediction;
  if (!p) {
    return (
      <section className="panel intel" id="prediction" aria-labelledby="prediction-title">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Predictive intelligence</p>
            <h2 id="prediction-title">Prediction and risk</h2>
          </div>
        </div>
        <p className="empty">Waiting for telemetry.</p>
      </section>
    );
  }
  const [tone, label, Icon] = RISK[p.risk] || RISK.LOW;
  const m = p.metrics;
  const disabled = !online || !!command.pending;
  const headline = predictiveHeadline(telemetry);
  const focus =
    p.tracks.find((t) => t.id === p.track) || p.tracks.find((t) => t.moving && t.state === 'confirmed') || p.tracks[0] || null;
  const movingCount = p.tracks.filter((t) => t.moving).length;
  const speedPct = Math.round((p.speed_factor ?? 1) * 100);

  return (
    <section className={`panel intel intel-${headline[0]}`} id="prediction" aria-labelledby="prediction-title">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Predictive intelligence</p>
          <h2 id="prediction-title">Prediction and risk</h2>
        </div>
        <div className="intel-head-tools">
          <span className="chip">
            {p.tracks.length} tracked &middot; {movingCount} moving
          </span>
          <label className={`switch${p.enabled ? ' on' : ''}`}>
            <input
              type="checkbox"
              checked={p.enabled}
              disabled={disabled}
              onChange={(e) =>
                command.run('predictive', () => api.configure({ predictive: e.target.checked }), () =>
                  e.target.checked ? 'Predictive avoidance on' : 'Predictive avoidance off: reactive baseline',
                )
              }
            />
            <span className="switch-track" aria-hidden="true" />
            Predictive avoidance
          </label>
        </div>
      </div>

      <Pipeline telemetry={telemetry} />

      <div className="intel-grid">
        <div className={`risk-card risk-${tone}`} role="status" aria-live="polite">
          <p className={`intel-state tone-${headline[0]}`}>
            <span className="intel-state-mark" aria-hidden="true" />
            <strong>{headline[1]}</strong>
            <span>{headline[2]}</span>
          </p>
          <span className="risk-badge">
            <Icon size={16} />
            <span>
              <Term tip="A rule-based estimate from a constant-velocity prediction (HIGH: conflict predicted within 1.5 s; MEDIUM: within 3 s, or an uncertain track near the route; LOW: neither). It is not a probability of collision and does not guarantee safety.">
                Risk
              </Term>{' '}
              <strong>{label}</strong>
            </span>
          </span>
          <RiskMeter risk={p.risk} />
          <div className="risk-body">
            <p className="risk-action">
              <span className="muted small">Robot response</span>
              <strong>{ACTION[p.action] || p.action}</strong>
            </p>
            <div className="speed-gauge" aria-label={`Commanded speed ${speedPct}% of the planned speed`}>
              <span className="muted small">Commanded speed</span>
              <div className="sg-bar">
                <span style={{ width: `${speedPct}%` }} />
              </div>
              <span className="mono">{speedPct}%</span>
            </div>
            <p className="risk-reason">
              <span className="muted small">Why</span>
              {p.reason}
            </p>
          </div>
        </div>

        <div className="intel-horizon">
          <div className="ttc">
            <span className="muted small">
              <Term tip="Time until the robot and the tracked object are predicted to come closer than robot radius + object radius + safety margin + prediction uncertainty, if both keep their current velocity. Shown only for confirmed moving tracks.">
                Time to conflict
              </Term>
            </span>
            <strong className="mono">{p.ttc != null ? `${p.ttc.toFixed(1)} s` : '—'}</strong>
            <span className="muted small">{p.ttc != null ? `track T${p.track}` : 'none predicted within 3 s'}</span>
          </div>
          <HorizonBar ttc={p.ttc} />
          <div className="pred-strip">
            <p className="muted small">
              {focus ? (
                <>
                  Predicted positions of <strong>T{focus.id}</strong> ({focus.label}
                  {focus.moving ? `, ${focus.speed.toFixed(2)} m/s, heading ${focus.heading_deg}°` : ', static'})
                </>
              ) : (
                'No tracked object to predict'
              )}
            </p>
            {focus && focus.moving ? (
              <ol className="pred-cells">
                {focus.predicted.map((q) => (
                  <li key={q.t}>
                    <span className="pc-t mono">+{q.t} s</span>
                    <span className="pc-xy mono">
                      {q.x.toFixed(1)}, {q.y.toFixed(1)}
                    </span>
                    <span className="pc-sig mono">&plusmn;{q.sigma.toFixed(2)} m</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="pred-empty small">{focus ? 'Static objects are not extrapolated.' : 'Objects outside the prior map appear here once LiDAR confirms them.'}</p>
            )}
          </div>
        </div>

        <figure className="intel-radar">
          <ConflictRadar telemetry={telemetry} focus={focus} />
          <figcaption className="radar-legend small">
            <span><i className="lg lg-route" />Route ahead</span>
            <span><i className="lg lg-pred" />Predicted path (0.5–3 s) &plusmn; uncertainty</span>
            <span><i className="lg lg-conflict" />Predicted conflict</span>
          </figcaption>
        </figure>
      </div>

      <details className="intel-details">
        <summary>Tracked objects and prediction quality</summary>
        <div className="table-wrap">
          <table className="data">
            <caption className="sr-only">Tracked objects</caption>
            <thead>
              <tr>
                <th scope="col">Track</th>
                <th scope="col">State</th>
                <th scope="col">Speed</th>
                <th scope="col">
                  <Term tip="0-1, from how consistently the object has been observed, how recently, and how certain its velocity is.">Confidence</Term>
                </th>
                <th scope="col">Risk</th>
                <th scope="col">TTC</th>
              </tr>
            </thead>
            <tbody>
              {p.tracks.length ? (
                p.tracks.map((t) => (
                  <tr key={t.id}>
                    <th scope="row">
                      T{t.id} <span className="muted small">{t.label}</span>
                    </th>
                    <td className="small">{STATE[t.state] || t.state}</td>
                    <td className="mono small">{t.moving ? `${t.speed.toFixed(2)} m/s, ${t.heading_deg}°` : 'static'}</td>
                    <td className="mono small">{Math.round(t.confidence * 100)}%</td>
                    <td>
                      <span className={`risk-tag risk-tag-${t.risk.toLowerCase()}`}>{t.risk}</span>
                    </td>
                    <td className="mono small">{t.ttc != null ? `${t.ttc.toFixed(1)} s` : '—'}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="muted small">
                    No objects outside the prior map are in LiDAR view.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <dl className="kv-grid map-kv">
          <div className="kv">
            <dt>
              <Term tip="Distance between each 1 s-ahead prediction and where the object actually was 1 s later. Measured against the simulator's ground truth, so it exists only in simulation.">
                1 s prediction error
              </Term>
            </dt>
            <dd className="mono">
              mean {fmt(m.prediction_error_1s_mean, 2, ' m')}, max {fmt(m.prediction_error_1s_max, 2, ' m')} ({m.prediction_samples})
            </dd>
          </div>
          <div className="kv">
            <dt>Closest approach to a moving obstacle</dt>
            <dd className="mono">{fmt(m.min_moving_clearance, 2, ' m')}</dd>
          </div>
          <div className="kv">
            <dt>Near misses (&lt; 0.25 m)</dt>
            <dd className="mono">{m.near_misses}</dd>
          </div>
          <div className="kv">
            <dt>Tracks lost</dt>
            <dd className="mono">{m.tracks_lost}</dd>
          </div>
          <div className="kv">
            <dt>Tracking time per scan</dt>
            <dd className="mono">
              {fmt(m.tracking_ms_mean, 1, ' ms')} (max {fmt(m.tracking_ms_max, 1, ' ms')})
            </dd>
          </div>
        </dl>
      </details>
      <p className="muted small intel-note">
        <InfoIcon size={12} /> {p.source}. Predictions assume constant velocity, so they are least accurate when an object turns.
        Collision safety does not depend on this layer: the route check, proximity stop and safety veto stay active.
      </p>
    </section>
  );
}
