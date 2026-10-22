import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { CheckIcon, PlayIcon, ResetIcon, WarningIcon } from './Icons';

const SCENARIO = 'crossing';
const TARGET = { x: 18.5, y: 6.0 };
const ACT = /slowing|waiting|stepping aside|stopped|replanning/i;
const RESUME = /resuming/i;

/**
 * Eight-step judge walkthrough on the live crossing scenario. The demo only sets up the
 * scenario and starts the mission through the normal API; every later step is ticked from
 * backend telemetry or the backend event log (which survives short-lived states that a slow
 * browser might not render), never from a timer.
 */
export function JudgeDemo({ telemetry, command, online, evaluation }) {
  const [mode, setMode] = useState('predictive');
  const [run, setRun] = useState(null); // null = not started; otherwise { mode, seen: {...} }
  const p = telemetry?.prediction;
  const m = telemetry?.mission;

  useEffect(() => {
    if (!run || !telemetry || telemetry.scenario !== SCENARIO) return;
    const seen = { ...run.seen };
    const events = telemetry.events || [];
    const predictive = run.mode === 'predictive';
    if (!seen.env && telemetry.target && Math.abs(telemetry.target.x - TARGET.x) < 0.01) {
      seen.env = `Crossing corridor loaded; destination (${TARGET.x}, ${TARGET.y}) at the exit`;
    }
    if (seen.env && !seen.route && run.started && telemetry.path?.length >= 2) {
      seen.route = `A* route: ${telemetry.path.length} waypoints${telemetry.last_plan?.length_m ? `, ${telemetry.last_plan.length_m} m` : ''}`;
    }
    const mover = p?.tracks.find((t) => t.moving && t.state === 'confirmed');
    if (seen.route && !seen.tracked && mover) {
      seen.tracked = `LiDAR track T${mover.id} (${mover.label}) moving at ${mover.speed.toFixed(2)} m/s`;
    }
    if (seen.tracked && !seen.trajectory && mover?.predicted?.length) {
      const last = mover.predicted[mover.predicted.length - 1];
      seen.trajectory = `T${mover.id} predicted at (${last.x.toFixed(1)}, ${last.y.toFixed(1)}) ± ${last.sigma.toFixed(2)} m in ${last.t} s`;
    }
    const conflict = events.find((e) => e.type === 'prediction' && e.data && (e.data.risk === 'MEDIUM' || e.data.risk === 'HIGH'));
    if (seen.route && !seen.risk) {
      if (conflict) {
        seen.risk = `Risk ${conflict.data.risk}${conflict.data.ttc != null ? `, conflict in ${conflict.data.ttc.toFixed(1)} s` : ''} (t = ${conflict.sim_time.toFixed(1)} s)`;
        seen.riskEvent = conflict.id;
      } else if (p && p.ttc != null && p.risk !== 'LOW') {
        seen.risk = `Risk ${p.risk}, conflict in ${p.ttc.toFixed(1)} s`;
        seen.riskEvent = events.length ? events[events.length - 1].id : 0;
      }
    }
    if (seen.risk && !seen.response) {
      // The response must follow the assessment; prefer the predictive layer's own decision.
      const later = events.filter((e) => e.id >= (seen.riskEvent ?? 0));
      const acted = predictive
        ? later.find((e) => e.type === 'prediction' && ACT.test(e.message)) ||
          later.find((e) => e.type === 'obstruction' || e.type === 'replanned')
        : later.find((e) => e.type === 'obstruction' || e.type === 'safety_stop' || e.type === 'collision');
      if (acted) seen.response = { id: acted.id, text: `${acted.message} (t = ${acted.sim_time.toFixed(1)} s)` };
    }
    if (seen.response && !seen.resumed) {
      const after = events.find((e) => e.id > seen.response.id && (RESUME.test(e.message) || e.type === 'replanned'));
      if (after) seen.resumed = `${after.message} (t = ${after.sim_time.toFixed(1)} s)`;
      else if (m?.status === 'goal_reached') seen.resumed = 'Continued to the destination';
    }
    if (!seen.outcome && run.started) {
      if (m?.status === 'goal_reached') {
        seen.outcome = { ok: true, text: `Goal reached in ${m.elapsed.toFixed(1)} s, ${m.replans} replans, ${telemetry.safety.collisions} collisions` };
      } else if (m && (m.status === 'stopped' || m.status === 'error' || (m.status === 'blocked' && !m.waiting))) {
        seen.outcome = { ok: false, text: `Mission ended as ${m.status}${m.reason ? `: ${m.reason}` : ''}; collisions ${telemetry.safety.collisions}` };
      }
    }
    if (JSON.stringify(seen) !== JSON.stringify(run.seen)) setRun((r) => r && { ...r, seen });
  }, [telemetry]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setRun({ mode, started: false, seen: {} });
    const setup = [
      () => api.reset(SCENARIO),
      () => api.configure({ predictive: mode === 'predictive' }),
      () => api.setTarget(TARGET.x, TARGET.y),
    ];
    for (const step of setup) {
      if (!(await command.run('judge-demo', step, null))) return setRun(null);
    }
    if (!(await command.run('judge-demo', () => api.navigate(), () => `Judge demo started (${mode === 'predictive' ? 'predictive' : 'reactive baseline'})`))) {
      return setRun(null);
    }
    setRun((r) => r && { ...r, started: true });
  };

  const seen = run?.seen || {};
  const predictive = (run?.mode || mode) === 'predictive';
  const steps = [
    ['env', 'Environment and destination', 'Load the crossing corridor and select the exit as the destination.'],
    ['route', 'Navigation starts on a planned route', 'A* plans on the occupancy grid; the route appears in the viewport.'],
    ['tracked', 'A moving pedestrian is detected and tracked', 'LiDAR returns off the prior map become a Kalman-filtered track.'],
    ['trajectory', 'Its trajectory is estimated', 'Positions 0.5–3 s ahead, with uncertainty, are drawn in the viewport and the radar.'],
    ['risk', 'A potential conflict is assessed', 'The robot rollout is checked against each prediction: risk level and time to conflict.'],
    [
      'response',
      predictive ? 'The robot responds before the conflict' : 'The baseline reacts only when obstructed',
      predictive ? 'Slow, wait, step aside or replan around the predicted path, with the reason logged.' : 'Predictions are shown but not acted on; only the reactive layers respond.',
    ],
    ['resumed', 'It continues once the way is clear', 'Normal speed or a new route is resumed after the conflict passes.'],
    ['outcome', 'Mission result', 'Reported from telemetry: goal reached, or how and why it ended.'],
  ];
  const firstOpen = steps.findIndex(([k]) => !seen[k]);
  const outcome = seen.outcome;
  const cmp = evaluation?.comparison;

  return (
    <section className="panel judge" id="judge-demo" aria-labelledby="judge-title">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Judge demo</p>
          <h2 id="judge-title">Predictive crossing, live</h2>
        </div>
      </div>
      <p className="muted small">
        A person walks across the robot&rsquo;s route and does not give way. Run it with predictive avoidance, then with the reactive
        baseline, and compare. Steps are confirmed only by the backend.
      </p>
      <div className="judge-controls">
        <div className="tool-group" role="group" aria-label="Navigation mode for the demo">
          {[
            ['predictive', 'Predictive'],
            ['reactive', 'Reactive baseline'],
          ].map(([v, text]) => (
            <button key={v} type="button" className={`tool-btn${mode === v ? ' on' : ''}`} aria-pressed={mode === v} onClick={() => setMode(v)}>
              {text}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn-primary" disabled={!online || !!command.pending} onClick={start}>
          {run ? <ResetIcon size={15} /> : <PlayIcon size={15} />}
          {run ? 'Run judge demo again' : 'Run judge demo'}
        </button>
      </div>
      {run && (
        <ol className="judge-steps" aria-live="polite">
          {steps.map(([key, title, hint], i) => {
            const value = seen[key];
            const done = !!value;
            const failed = key === 'outcome' && value && !value.ok;
            const state = failed ? 'failed' : done ? 'done' : i === firstOpen ? 'current' : 'todo';
            const detail = typeof value === 'object' && value ? value.text : value;
            return (
              <li key={key} className={`js-step js-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
                <span className="js-mark" aria-hidden="true">
                  {failed ? <WarningIcon size={13} /> : done ? <CheckIcon size={13} /> : i + 1}
                </span>
                <div>
                  <p className="js-title">
                    {title}
                    <span className="sr-only">{done ? ' (confirmed from telemetry)' : state === 'current' ? ' (waiting)' : ''}</span>
                  </p>
                  <p className={done ? 'js-detail' : 'js-hint'}>{done ? detail : hint}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {outcome && cmp && (
        <div className="judge-evidence">
          <p className="small">
            <strong>Recorded evaluation</strong> ({cmp.predictive.runs} runs per mode, same scenario family): predictive reached the goal{' '}
            <strong className="mono">{cmp.predictive.goal_completion}</strong> with <strong className="mono">{cmp.predictive.collisions_total}</strong>{' '}
            collisions; reactive <strong className="mono">{cmp.reactive.goal_completion}</strong> with{' '}
            <strong className="mono">{cmp.reactive.collisions_total}</strong>.
          </p>
          <a className="btn btn-sm" href="#evaluation">
            Open the comparison
          </a>
        </div>
      )}
    </section>
  );
}
