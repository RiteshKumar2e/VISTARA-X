import { api } from '../services/api';
import { PauseIcon, PlayIcon, StopIcon } from './Icons';
import { CommandButton } from './MissionControls';
import { MissionStatusBadge } from './StatusBadge';
import { Term } from './Term';

const RUNNING = new Set(['planning', 'navigating', 'replanning']);

function Health({ label, ok, text }) {
  const tone = ok === true ? 'ok' : ok === false ? 'bad' : 'warn';
  return (
    <li className={`ov-health ${tone}`}>
      <span className="ov-dot" aria-hidden="true" />
      <span className="ov-health-label">{label}</span>
      <span className="ov-health-text">{text}</span>
      <span className="sr-only">{tone === 'ok' ? '(ok)' : tone === 'bad' ? '(problem)' : '(pending)'}</span>
    </li>
  );
}

/** Command bar: mission state, scenario, destination, link health and the main quick controls. */
export function MissionOverview({ telemetry, backend, connection, command, online, demoMode, onDemoMode, scenarios = [], onJudgeDemo }) {
  const m = telemetry?.mission;
  const status = m?.status;
  const running = RUNNING.has(status) || m?.waiting;
  const { pending, run } = command;
  const sensors = telemetry?.sensors?.sensors ?? [];
  const sensorsOk = sensors.filter((s) => s.health === 'ok').length;
  const enabled = sensors.filter((s) => s.enabled).length;
  const scenario = scenarios.find((s) => s.key === telemetry?.scenario);
  const target = telemetry?.target;

  return (
    <section className="overview-strip command-bar" aria-labelledby="overview-title">
      <h2 id="overview-title" className="sr-only">
        Mission overview
      </h2>
      <div className="cb-state">
        {telemetry ? <MissionStatusBadge status={status} waiting={m.waiting} /> : <span className="badge badge-neutral">No telemetry</span>}
        <div className="cb-facts">
          <span className="cb-fact">
            <span className="cb-k">Scenario</span>
            <span className="cb-v">{scenario?.name || telemetry?.scenario || '—'}</span>
          </span>
          <span className="cb-fact">
            <span className="cb-k">Destination</span>
            <span className="cb-v mono">{target ? `${target.x.toFixed(1)}, ${target.y.toFixed(1)}` : 'not set'}</span>
          </span>
          {telemetry && (
            <span className="cb-fact">
              <span className="cb-k">Progress</span>
              <span className="cb-v mono">
                {telemetry.distance_to_target !== null ? `${telemetry.distance_to_target.toFixed(1)} m to go` : '—'}
                {m.progress !== null ? ` · ${Math.round(m.progress * 100)}%` : ''} · {m.replans} replans
              </span>
            </span>
          )}
        </div>
        {/* Always rendered (empty when there is no reason) so the bar never changes height. */}
        <span className="small ov-reason" title={m?.reason || undefined}>
          {m?.reason || ' '}
        </span>
      </div>
      <div className="cb-actions">
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
        <span className="cb-sep" aria-hidden="true" />
        <button type="button" className="btn btn-accent-outline" onClick={onJudgeDemo} disabled={!online}>
          Judge demo
        </button>
        <span className="ov-demo">
          <label className="check">
            <input type="checkbox" checked={!!demoMode} disabled={!online || !!pending} onChange={(e) => onDemoMode(e.target.checked)} />
            Demo mode
          </label>
          <Term tip="For slower laptops and live presentations: the 3D view renders at 20 fps without shadows at a pixel ratio of 1, and the robot's maximum speed is set to 0.6 m/s. Turning it off restores the previous speed.">
            <span aria-hidden="true">?</span>
            <span className="sr-only">About demo mode</span>
          </Term>
        </span>
      </div>
      <ul className="ov-health-list" aria-label="System health summary">
        <Health label="Backend" ok={backend.state === 'ok' ? true : backend.state === 'down' ? false : null} text={backend.state === 'ok' ? 'online' : backend.state === 'down' ? 'unreachable' : 'checking'} />
        <Health label="Telemetry" ok={connection === 'open' ? true : connection === 'closed' ? false : null} text={{ open: 'live', stale: 'delayed', connecting: 'connecting', closed: 'offline' }[connection]} />
        {telemetry && <Health label="Physics" ok text={telemetry.safety.physics === 'pybullet' ? 'PyBullet' : 'analytic 2D'} />}
        {telemetry && <Health label="Sensors" ok={sensorsOk === enabled && enabled > 0 ? true : sensorsOk === 0 ? false : null} text={`${sensorsOk}/${sensors.length} simulated`} />}
        {telemetry && <Health label="Collisions" ok={telemetry.safety.collisions === 0} text={String(telemetry.safety.collisions)} />}
      </ul>
    </section>
  );
}
