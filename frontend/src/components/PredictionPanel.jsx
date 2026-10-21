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
  monitor_only: 'Monitoring only (reactive baseline)',
};
const STATE = { confirmed: 'Tracked', coasting: 'Uncertain (not seen)', tentative: 'New' };

const fmt = (v, d = 2, unit = '') => (v === null || v === undefined ? '—' : `${Number(v).toFixed(d)}${unit}`);

/** Predictive avoidance: tracked objects, predictions, risk and the decision taken. */
export function PredictionPanel({ telemetry, online, command }) {
  const p = telemetry?.prediction;
  if (!p) {
    return (
      <section className="panel" id="prediction" aria-labelledby="prediction-title">
        <div className="panel-head">
          <h2 id="prediction-title">Prediction and risk</h2>
        </div>
        <p className="empty">Waiting for telemetry.</p>
      </section>
    );
  }
  const [tone, label, Icon] = RISK[p.risk] || RISK.LOW;
  const m = p.metrics;
  const disabled = !online || !!command.pending;
  return (
    <section className="panel prediction" id="prediction" aria-labelledby="prediction-title">
      <div className="panel-head">
        <h2 id="prediction-title">Prediction and risk</h2>
        <label className="check">
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
          Predictive avoidance
        </label>
      </div>

      <div className={`risk-card risk-${tone}`} role="status" aria-live="polite">
        <span className="risk-badge">
          <Icon size={18} />
          <span>
            <Term tip="A rule-based estimate from a constant-velocity prediction (HIGH: conflict predicted within 1.5 s; MEDIUM: within 3 s, or an uncertain track near the route; LOW: neither). It is not a probability of collision and does not guarantee safety.">
              Risk
            </Term>{' '}
            <strong>{label}</strong>
          </span>
        </span>
        <div className="risk-body">
          <p className="risk-action">
            <strong>{ACTION[p.action] || p.action}</strong>
            {p.enabled && p.speed_factor < 1 && p.speed_factor > 0 ? ` (${Math.round(p.speed_factor * 100)}% speed)` : ''}
          </p>
          <p className="risk-reason">{p.reason}</p>
          {p.ttc != null && (
            <p className="mono small">
              <Term tip="Time until the robot and the tracked object are predicted to come closer than robot radius + object radius + safety margin + prediction uncertainty, if both keep their current velocity. Shown only for confirmed moving tracks.">
                Time to conflict
              </Term>{' '}
              {p.ttc.toFixed(1)} s (track {p.track})
            </p>
          )}
        </div>
      </div>

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
      <p className="muted small">
        <InfoIcon size={12} /> {p.source}. Predictions assume constant velocity, so they are least accurate when an object turns.
        Collision safety does not depend on this layer: the route check, proximity stop and safety veto stay active.
      </p>
    </section>
  );
}
