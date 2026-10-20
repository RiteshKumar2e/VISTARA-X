import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Term } from './Term';

const HEALTH = {
  ok: ['ok', 'Live'],
  waiting: ['pending', 'Waiting'],
  stale: ['degraded', 'Stale'],
  error: ['down', 'Error'],
  disabled: ['pending', 'Off'],
};

const ACTION = {
  clear: ['ok', 'Clear'],
  slow: ['degraded', 'Slowing'],
  stop: ['down', 'Stopped'],
  degraded: ['degraded', 'Fail-safe speed'],
};

const n = (v, d = 2, unit = '') => (v === null || v === undefined ? 'Unavailable' : `${Number(v).toFixed(d)}${unit}`);

function summary(s) {
  const r = s.reading;
  if (!s.enabled) return 'disabled';
  if (!r) return 'no reading yet';
  switch (s.key) {
    case 'camera':
      return `frame ${r.frame}, ${r.detections} detection(s)`;
    case 'depth':
      return `nearest object ${n(r.nearest_m, 1, ' m')}`;
    case 'lidar':
      return `${r.valid_returns}/${r.rays} returns, front ${n(r.front_min, 2, ' m')}`;
    case 'ultrasonic':
      return `front ${n(r.front_min, 2, ' m')}, ${r.channels.filter((c) => c.detected).length}/${r.channels.length} channels detecting`;
    case 'imu':
      return `yaw ${n(r.yaw_deg, 1, '°')}, rate ${n(r.yaw_rate, 2, ' rad/s')}, drift ${n(r.yaw_drift_deg, 2, '°')}`;
    case 'odometry':
      return `estimate (${n(r.estimate.x, 2)}, ${n(r.estimate.y, 2)}), drift ${n(r.drift_m, 2, ' m')}`;
    default:
      return '';
  }
}

/** All sensors are simulated; this panel says so and never presents them as hardware. */
export function SensorsPanel({ telemetry, command, online }) {
  const [lidar, setLidar] = useState(null);
  const [safety, setSafety] = useState(null);
  const sensorsData = telemetry?.sensors;
  const p = telemetry?.perception;

  const list = sensorsData
    ? [
        {
          key: 'camera',
          name: 'RGB camera (simulated render)',
          enabled: p.enabled,
          health: !p.enabled ? 'disabled' : p.stale ? 'stale' : p.frame_seq ? 'ok' : 'waiting',
          rate_hz: p.rate_hz,
          age_s: null,
          reading: { frame: p.frame_seq, detections: p.detections.length },
        },
        {
          key: 'depth',
          name: `Depth (simulated, ${p.renderer === 'pybullet' ? 'PyBullet depth buffer' : 'ray-cast'})`,
          enabled: p.enabled,
          health: !p.enabled ? 'disabled' : p.stale ? 'stale' : p.frame_seq ? 'ok' : 'waiting',
          rate_hz: p.rate_hz,
          age_s: null,
          reading: { nearest_m: p.scene?.nearest?.distance ?? null },
          readonly: true,
        },
        ...sensorsData.sensors,
      ]
    : [];

  const lidarStatus = sensorsData?.sensors.find((s) => s.key === 'lidar');
  useEffect(() => {
    if (lidarStatus && !lidar) setLidar({ fov_deg: lidarStatus.config.fov_deg, max_range: lidarStatus.config.max_range, resolution_deg: lidarStatus.config.resolution_deg });
    if (sensorsData && !safety) setSafety({ slow_distance: sensorsData.policy.slow_distance, stop_distance: sensorsData.policy.stop_distance });
  }, [lidarStatus, sensorsData, lidar, safety]);

  if (!sensorsData) {
    return (
      <section className="panel" aria-labelledby="sensors-title">
        <div className="panel-head">
          <h2 id="sensors-title">Sensors</h2>
        </div>
        <p className="empty">Waiting for sensor telemetry.</p>
      </section>
    );
  }

  const prox = sensorsData.proximity;
  const [tone, label] = ACTION[prox.action] || ['pending', prox.action];
  const disabled = !online || !!command.pending;

  const toggle = (s, enabled) =>
    s.key === 'camera'
      ? command.run('sensor', () => api.configurePerception({ enabled }), () => `Camera ${enabled ? 'enabled' : 'disabled'}`)
      : command.run('sensor', () => api.configureSensor(s.key, { enabled }), () => `${s.name} ${enabled ? 'enabled' : 'disabled'}`);

  return (
    <section className="panel sensors" aria-labelledby="sensors-title">
      <div className="panel-head">
        <h2 id="sensors-title">Sensors</h2>
        <span className="tag tag-accent">
          <span className="tag-mark" aria-hidden="true" />
          All simulated
        </span>
      </div>
      <p className="hint hint-top">
        Every sensor measures the simulator&rsquo;s geometry with a seeded noise model. No physical hardware is connected.
      </p>

      <div className={`prox prox-${tone}`} role="status">
        <span className="prox-label">
          <Term tip="Measured clearance in the robot's driving corridor (robot width, up to the next waypoint), from the simulated LiDAR and the forward ultrasonic channel. Below the slow distance the speed is reduced; below the stop distance forward motion stops and a replan is requested.">
            Proximity safety
          </Term>
        </span>
        <strong>{label}</strong>
        <span className="mono">
          {prox.front_clearance !== null ? `${prox.front_clearance.toFixed(2)} m ahead` : 'nothing in corridor'}
          {' · '}speed &times;{prox.speed_factor.toFixed(2)}
        </span>
        <span className="muted small">
          {prox.sources.length ? `sources: ${prox.sources.join(' + ')}` : 'no fresh proximity sensor'} &middot; stops this mission:{' '}
          {sensorsData.proximity_stops}
        </span>
      </div>

      <div className="table-wrap">
        <table className="data sensor-table">
          <thead>
            <tr>
              <th scope="col">Sensor</th>
              <th scope="col">State</th>
              <th scope="col">Rate</th>
              <th scope="col">Latest measurement</th>
              <th scope="col">On</th>
            </tr>
          </thead>
          <tbody>
            {list.map((s) => {
              const [htone, htext] = HEALTH[s.health] || ['pending', s.health];
              return (
                <tr key={s.key}>
                  <th scope="row">{s.name}</th>
                  <td>
                    <span className={`sys-inline sys-${htone}`}>{htext}</span>
                    {s.age_s !== null && s.age_s !== undefined && <span className="muted small mono"> {s.age_s.toFixed(2)} s</span>}
                    {s.error && <span className="field-error"> {s.error}</span>}
                  </td>
                  <td className="mono">{s.rate_hz} Hz</td>
                  <td className="small">{summary(s)}</td>
                  <td>
                    {!s.readonly && (
                      <input
                        type="checkbox"
                        aria-label={`Enable ${s.name}`}
                        checked={s.enabled}
                        disabled={disabled}
                        onChange={(e) => toggle(s, e.target.checked)}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <details className="explain">
        <summary>LiDAR and safety thresholds</summary>
        {lidar && (
          <form
            className="sensor-form"
            onSubmit={(e) => {
              e.preventDefault();
              command.run('sensor', () => api.configureSensor('lidar', { params: lidar }), () => 'LiDAR configured');
            }}
          >
            {[
              ['fov_deg', 'Scan angle', 30, 360, 10, '°'],
              ['resolution_deg', 'Angular resolution', 0.5, 5, 0.5, '°'],
              ['max_range', 'Max range', 2, 15, 0.5, ' m'],
            ].map(([key, text, min, max, step, unit]) => (
              <div className="field" key={key}>
                <label htmlFor={`lidar-${key}`}>
                  {text} <span className="mono">{lidar[key]}{unit}</span>
                </label>
                <input
                  id={`lidar-${key}`}
                  type="range"
                  min={min}
                  max={max}
                  step={step}
                  value={lidar[key]}
                  onChange={(e) => setLidar((l) => ({ ...l, [key]: Number(e.target.value) }))}
                />
              </div>
            ))}
            <button type="submit" className="btn" disabled={disabled}>
              Apply LiDAR settings
            </button>
          </form>
        )}
        {safety && (
          <form
            className="sensor-form"
            onSubmit={(e) => {
              e.preventDefault();
              command.run('sensor', () => api.configureSensor('safety', { params: safety }), () => 'Safety thresholds applied');
            }}
          >
            {[
              ['slow_distance', 'Slow below', 0.3, 2.5],
              ['stop_distance', 'Stop below', 0.1, 1.2],
            ].map(([key, text, min, max]) => (
              <div className="field" key={key}>
                <label htmlFor={`safety-${key}`}>
                  {text} <span className="mono">{safety[key].toFixed(2)} m</span>
                </label>
                <input
                  id={`safety-${key}`}
                  type="range"
                  min={min}
                  max={max}
                  step="0.05"
                  value={safety[key]}
                  onChange={(e) => setSafety((v) => ({ ...v, [key]: Number(e.target.value) }))}
                />
              </div>
            ))}
            <button type="submit" className="btn" disabled={disabled}>
              Apply thresholds
            </button>
          </form>
        )}
      </details>
    </section>
  );
}
