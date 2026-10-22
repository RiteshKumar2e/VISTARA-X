import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { PauseIcon, PlayIcon, StopIcon } from './Icons';
import { CommandButton } from './MissionControls';
import { MissionStatusBadge } from './StatusBadge';
import { Term } from './Term';

const SECTIONS = [
  ['simulator', 'Simulator'],
  ['prediction', 'Prediction'],
  ['commands', 'Commands'],
  ['mapping', 'Mapping'],
  ['controls', 'Controls'],
  ['challenge', 'Challenge'],
  ['perception', 'Perception'],
  ['sensors', 'Sensors'],
  ['navigation', 'Navigation'],
  ['telemetry', 'Telemetry'],
  ['events', 'Events'],
  ['health', 'Health'],
];
const RUNNING = new Set(['planning', 'navigating', 'replanning']);

function Health({ label, ok, text }) {
  return (
    <li className={`ov-health ${ok === true ? 'ok' : ok === false ? 'bad' : 'warn'}`}>
      <span className="ov-dot" aria-hidden="true" />
      <span className="muted">{label}</span> {text}
    </li>
  );
}

/** Live summary at the top of the console: state, quick controls, health, section links. */
export function MissionOverview({ telemetry, backend, connection, command, online, demoMode, onDemoMode }) {
  const m = telemetry?.mission;
  const status = m?.status;
  const running = RUNNING.has(status) || m?.waiting;
  const { pending, run } = command;
  const sensors = telemetry?.sensors?.sensors ?? [];
  const sensorsOk = sensors.filter((s) => s.health === 'ok').length;
  const enabled = sensors.filter((s) => s.enabled).length;

  return (
    <section className="overview-strip panel" aria-labelledby="overview-title">
      <h2 id="overview-title" className="sr-only">
        Mission overview
      </h2>
      <div className="ov-row">
        <div className="ov-status">
          {telemetry ? <MissionStatusBadge status={status} waiting={m.waiting} /> : <span className="muted">No telemetry</span>}
          {telemetry && (
            <span className="mono small">
              {telemetry.distance_to_target !== null ? `${telemetry.distance_to_target.toFixed(2)} m to target` : 'no target'}
              {m.progress !== null ? ` · ${Math.round(m.progress * 100)}% of route` : ''} &middot; replans {m.replans}
            </span>
          )}
          {m?.reason && (
            <span className="small ov-reason" title={m.reason}>
              {m.reason}
            </span>
          )}
        </div>
        <div className="button-row ov-actions">
          <CommandButton
            name="start"
            pending={pending}
            icon={PlayIcon}
            className="btn btn-primary"
            disabled={!online || !telemetry?.target || running || status === 'paused' || !!pending}
            onClick={() => run('start', () => api.navigate(), () => 'Mission started')}
          >
            Start
          </CommandButton>
          {status === 'paused' ? (
            <CommandButton name="resume" pending={pending} icon={PlayIcon} disabled={!online || !!pending} onClick={() => run('resume', api.resume, () => 'Mission resumed')}>
              Resume
            </CommandButton>
          ) : (
            <CommandButton name="pause" pending={pending} icon={PauseIcon} disabled={!online || !running || !!pending} onClick={() => run('pause', api.pause, () => 'Mission paused')}>
              Pause
            </CommandButton>
          )}
          <CommandButton
            name="stop"
            pending={pending}
            icon={StopIcon}
            disabled={!online || !(running || status === 'paused') || !!pending}
            onClick={() => run('stop', api.stop, () => 'Mission stopped; robot halted')}
          >
            Halt
          </CommandButton>
          <span className="ov-demo">
            <label className="check">
              <input type="checkbox" checked={!!demoMode} disabled={!!pending} onChange={(e) => onDemoMode(e.target.checked)} />
              Demo mode
            </label>
            <Term tip="For slower laptops and live presentations: the 3D view renders at 20 fps without shadows at a pixel ratio of 1, and the robot's maximum speed is set to 0.6 m/s. Turning it off restores the previous speed.">
              <span aria-hidden="true">?</span>
              <span className="sr-only">About demo mode</span>
            </Term>
          </span>
        </div>
      </div>
      <ul className="ov-health-list" aria-label="System health summary">
        <Health label="Backend" ok={backend.state === 'ok' ? true : backend.state === 'down' ? false : null} text={backend.state === 'ok' ? 'online' : backend.state === 'down' ? 'unreachable' : 'checking'} />
        <Health label="Telemetry" ok={connection === 'open' ? true : connection === 'closed' ? false : null} text={{ open: 'live', stale: 'delayed', connecting: 'connecting', closed: 'offline' }[connection]} />
        {telemetry && <Health label="Physics" ok text={telemetry.safety.physics === 'pybullet' ? 'PyBullet' : 'analytic 2D'} />}
        {telemetry && <Health label="Sensors" ok={sensorsOk === enabled && enabled > 0 ? true : sensorsOk === 0 ? false : null} text={`${sensorsOk}/${sensors.length} live (simulated)`} />}
        {telemetry && <Health label="Collisions" ok={telemetry.safety.collisions === 0} text={String(telemetry.safety.collisions)} />}
      </ul>
      <nav className="ov-nav" aria-label="Console sections">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
        <Link to="/architecture">Project information</Link>
      </nav>
    </section>
  );
}
