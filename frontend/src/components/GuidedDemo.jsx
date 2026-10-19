import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

const DEMO_TARGET = { x: 18.5, y: 6.0 };
const MOVE_BEFORE_OBSTACLE = 1.5; // metres travelled before the obstacle is dropped

const EMPTY_RUN = { prepared: false, targetSet: false, started: false, injected: false };

/**
 * Guided judge demo. Every step calls the real backend and is marked complete only
 * when live telemetry confirms it, so the walkthrough cannot show a fake success.
 */
export function GuidedDemo({ telemetry, command, online, startSignal = 0 }) {
  const [run, setRun] = useState(EMPTY_RUN);
  const [auto, setAuto] = useState(false);
  const inFlight = useRef(false);

  const m = telemetry?.mission;
  const status = m?.status;
  const failed = run.started && ((status === 'blocked' && !m?.waiting) || status === 'stopped');

  const steps = [
    {
      key: 'prepare',
      title: 'Load the warehouse scenario',
      detail: 'Resets the robot to its start pose and removes added obstacles.',
      done: run.prepared,
      triggered: run.prepared,
      action: async () => {
        const ok = await command.run('demo', () => api.reset('warehouse'), () => 'Demo scenario ready');
        if (ok) setRun({ ...EMPTY_RUN, prepared: true });
      },
    },
    {
      key: 'target',
      title: 'Select the destination',
      detail: `Target (${DEMO_TARGET.x}, ${DEMO_TARGET.y}) at the far end of the aisle.`,
      done: run.targetSet && !!telemetry?.target,
      triggered: run.targetSet,
      action: async () => {
        const ok = await command.run(
          'demo',
          () => api.setTarget(DEMO_TARGET.x, DEMO_TARGET.y),
          () => 'Demo target selected',
        );
        if (ok) setRun((r) => ({ ...r, targetSet: true }));
      },
    },
    {
      key: 'start',
      title: 'Start the mission: A* plans a route',
      detail: 'The route and its waypoints appear on the map.',
      done: run.started && (telemetry?.path?.length ?? 0) >= 2,
      triggered: run.started,
      action: async () => {
        const ok = await command.run('demo', () => api.navigate(), () => 'Mission started');
        if (ok) setRun((r) => ({ ...r, started: true }));
      },
    },
    {
      key: 'move',
      title: 'Robot follows the route',
      detail: 'A pure-pursuit controller drives toward each waypoint.',
      done: run.started && (m?.distance_travelled ?? 0) >= MOVE_BEFORE_OBSTACLE,
    },
    {
      key: 'obstacle',
      title: 'Drop a dynamic obstacle on the route',
      detail: 'A barrier appears a few metres ahead, across the planned path.',
      done: run.injected,
      triggered: run.injected,
      action: async () => {
        const ok = await command.run('demo', api.injectObstacle, (r) => `Obstacle ${r.obstacle.id} dropped on the route`);
        if (ok) setRun((r) => ({ ...r, injected: true }));
      },
    },
    {
      key: 'replan',
      title: 'Obstruction detected: route replanned',
      detail: 'The occupancy grid updates and A* computes a new safe route.',
      done: run.injected && (m?.replans ?? 0) >= 1,
    },
    {
      key: 'goal',
      title: 'Goal reached',
      detail: 'Shown only when the robot is within 0.2 m of the target.',
      done: run.started && status === 'goal_reached',
    },
  ];

  const currentIndex = steps.findIndex((s) => !s.done);
  const current = steps[currentIndex];
  const finished = currentIndex === -1;

  // Auto-play: trigger the next actionable step once telemetry confirms the previous one.
  useEffect(() => {
    if (!auto || !online || !telemetry || inFlight.current || command.pending) return;
    if (finished || failed) {
      setAuto(false);
      return;
    }
    if (!current?.action || current.triggered) return; // waiting on the robot / telemetry
    inFlight.current = true;
    Promise.resolve(current.action()).finally(() => {
      inFlight.current = false;
    });
  });

  // Stop auto-play when a step fails (the command hook reports the error).
  useEffect(() => {
    if (auto && command.feedback?.kind === 'error') setAuto(false);
  }, [auto, command.feedback]);

  const startAuto = () => {
    setRun(EMPTY_RUN);
    setAuto(true);
  };

  // "Restart guided demo" from Mission controls.
  useEffect(() => {
    if (startSignal > 0) {
      setRun(EMPTY_RUN);
      setAuto(true);
      document.getElementById('demo-title')?.scrollIntoView({ block: 'nearest' });
    }
  }, [startSignal]);

  return (
    <section className="panel demo" aria-labelledby="demo-title">
      <div className="panel-head">
        <h2 id="demo-title">Guided demo</h2>
      </div>
      <p className="muted small">
        Runs the judging scenario on the live simulation. Each step completes only when telemetry confirms it.
      </p>
      <div className="button-row">
        <button type="button" className="btn btn-primary" onClick={startAuto} disabled={!online || auto}>
          {auto ? 'Running...' : run.prepared ? 'Restart guided demo' : 'Run guided demo'}
        </button>
        {auto ? (
          <button type="button" className="btn" onClick={() => setAuto(false)}>
            Pause walkthrough
          </button>
        ) : (
          current?.action &&
          !current.triggered &&
          !finished &&
          !failed && (
            <button
              type="button"
              className="btn"
              disabled={!online || !!command.pending}
              onClick={() => current.action()}
            >
              Next step
            </button>
          )
        )}
      </div>

      <ol className="steps">
        {steps.map((s, i) => {
          const state = s.done ? 'done' : i === currentIndex ? (failed ? 'failed' : 'current') : 'todo';
          return (
            <li key={s.key} className={`step step-${state}`} aria-current={state === 'current' ? 'step' : undefined}>
              <span className="step-mark" aria-hidden="true">
                {s.done ? '✓' : i + 1}
              </span>
              <div>
                <p className="step-title">
                  {s.title}
                  <span className="sr-only">
                    {state === 'done' ? ' (complete)' : state === 'current' ? ' (in progress)' : ''}
                  </span>
                </p>
                <p className="step-detail">{s.detail}</p>
              </div>
            </li>
          );
        })}
      </ol>
      <div role="status" aria-live="polite">
        {finished && <p className="feedback-msg feedback-success">Demo complete: goal reached after replanning.</p>}
        {failed && (
          <p className="feedback-msg feedback-error">
            The mission ended as {status === 'blocked' ? 'Blocked' : 'Stopped'}
            {m?.reason ? `: ${m.reason}` : ''}. Restart the demo to try again.
          </p>
        )}
      </div>
    </section>
  );
}
