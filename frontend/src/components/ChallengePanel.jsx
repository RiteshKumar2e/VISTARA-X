import { useEffect, useState } from 'react';
import { api } from '../services/api';

export const CHALLENGE_BUDGET = 5;
const CHALLENGE_TARGET = { x: 18.5, y: 6.0 };
const CHALLENGE_SPEED = 0.5; // m/s: gives a player time to place barriers ahead of the robot
const ACTIVE = new Set(['planning', 'navigating', 'replanning']);
const RECORDS_KEY = 'vistara.challengeRecords';

function readRecords() {
  try {
    return { games: 0, traps: 0, maxReplans: 0, ...JSON.parse(window.localStorage.getItem(RECORDS_KEY) || '{}') };
  } catch {
    return { games: 0, traps: 0, maxReplans: 0 };
  }
}
function saveRecords(r) {
  try {
    window.localStorage.setItem(RECORDS_KEY, JSON.stringify(r));
  } catch {
    /* storage unavailable: records are not kept */
  }
}

/**
 * "Trap the robot": the viewer gets a fixed number of barriers to place while the robot
 * drives. Every outcome is read from live telemetry: the robot either finds a way through
 * (replanning around each barrier) or reports BLOCKED, and the collision count is shown
 * throughout. The budget is a game rule enforced by this console, not by the backend.
 */
export function ChallengePanel({ telemetry, command, online, challenge, setChallenge, setClickMode, setObjectType }) {
  const [records, setRecords] = useState(readRecords);
  const m = telemetry?.mission;
  const active = !!challenge?.active;
  const result = challenge?.result;

  const restoreSpeed = (speed) => command.run('challenge', () => api.configure({ max_speed: speed }), null);

  const start = async () => {
    const prevSpeed = telemetry?.params?.max_speed ?? 0.9;
    const steps = [
      () => api.reset('warehouse'),
      () => api.configure({ max_speed: Math.min(CHALLENGE_SPEED, prevSpeed) }),
      () => api.setTarget(CHALLENGE_TARGET.x, CHALLENGE_TARGET.y),
      () => api.navigate(),
    ];
    for (const step of steps) {
      if (!(await command.run('challenge', step, null))) {
        await restoreSpeed(prevSpeed);
        return;
      }
    }
    setChallenge({ active: true, placed: 0, budget: CHALLENGE_BUDGET, prevSpeed, sawActive: false, result: null });
    setObjectType('barrier');
    setClickMode('obstacle');
    document.getElementById('simulator')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  const giveUp = () => command.run('challenge', api.stop, () => 'Challenge ended; robot halted');

  // Judge the outcome from telemetry, only after this challenge's mission was seen running.
  useEffect(() => {
    if (!active || !telemetry) return;
    const status = m.status;
    if (!challenge.sawActive) {
      if (ACTIVE.has(status)) setChallenge((c) => c && { ...c, sawActive: true });
      return;
    }
    let outcome = null;
    if (status === 'goal_reached') outcome = 'robot';
    else if (status === 'blocked' && !m.waiting) outcome = 'trapped';
    else if (status === 'stopped' || status === 'idle' || status === 'error') outcome = 'ended';
    if (!outcome) return;

    const res = {
      outcome,
      placed: challenge.placed,
      replans: m.replans,
      collisions: telemetry.safety.collisions,
      distance: m.distance_travelled,
      time: telemetry.sim_time,
      reason: m.reason,
    };
    setChallenge((c) => c && { ...c, active: false, result: res });
    setClickMode('target');
    restoreSpeed(challenge.prevSpeed);
    if (outcome !== 'ended') {
      const next = {
        games: records.games + 1,
        traps: records.traps + (outcome === 'trapped' ? 1 : 0),
        maxReplans: Math.max(records.maxReplans, res.replans),
      };
      setRecords(next);
      saveRecords(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [telemetry, active]);

  const left = active ? challenge.budget - challenge.placed : CHALLENGE_BUDGET;

  return (
    <section className="panel challenge" id="challenge" aria-labelledby="challenge-title">
      <div className="panel-head">
        <h2 id="challenge-title">Trap the robot</h2>
        <span className="tag tag-accent">
          <span className="tag-mark" aria-hidden="true" />
          Challenge
        </span>
      </div>
      <p className="muted small">
        You get {CHALLENGE_BUDGET} barriers. Place them on the floor while the robot drives to the far end of the aisle. Leave
        any gap and it will find it; seal it in and it has to admit it is <strong>Blocked</strong>. Either way, it must never
        touch an obstacle.
      </p>

      {!active && (
        <button type="button" className="btn btn-primary" disabled={!online || !!command.pending} onClick={start}>
          {result ? 'Play again' : 'Start challenge'}
        </button>
      )}

      {active && (
        <div className="ch-live" role="status" aria-live="polite">
          <div className="ch-budget">
            <span className="ch-pips" aria-hidden="true">
              {Array.from({ length: challenge.budget }, (_, i) => (
                <span key={i} className={`ch-pip${i < left ? ' on' : ''}`} />
              ))}
            </span>
            <strong>
              {left} of {challenge.budget} barriers left
            </strong>
          </div>
          <p className="hint">
            {left > 0
              ? 'Click the floor in the simulator to place a barrier (pick another object in the toolbar if you like).'
              : 'No barriers left. Watch what the robot does.'}
          </p>
          <dl className="ch-stats">
            <div>
              <dt>Replans forced</dt>
              <dd className="mono">{m?.replans ?? 0}</dd>
            </div>
            <div>
              <dt>Collisions</dt>
              <dd className="mono">{telemetry?.safety.collisions ?? 0}</dd>
            </div>
            <div>
              <dt>Robot status</dt>
              <dd>{m?.waiting ? 'waiting for a gap' : (m?.status ?? '').replace('_', ' ')}</dd>
            </div>
          </dl>
          <button type="button" className="btn" disabled={!!command.pending} onClick={giveUp}>
            Give up
          </button>
        </div>
      )}

      {!active && result && (
        <div className={`ch-result ch-${result.outcome}`} role="status" aria-live="polite">
          {result.outcome === 'robot' && (
            <p>
              <strong>The robot wins.</strong> It reached the goal after you placed {result.placed} barrier
              {result.placed === 1 ? '' : 's'} and forced {result.replans} replan{result.replans === 1 ? '' : 's'}.
            </p>
          )}
          {result.outcome === 'trapped' && (
            <p>
              <strong>You trapped it</strong> with {result.placed} barrier{result.placed === 1 ? '' : 's'} at t = {result.time.toFixed(1)} s. The
              robot did not force its way through; it reported Blocked: <em>{result.reason}</em>
            </p>
          )}
          {result.outcome === 'ended' && <p>Challenge ended before a result.</p>}
          <p className="mono small">
            collisions {result.collisions} &middot; distance {result.distance.toFixed(1)} m &middot; replans {result.replans}
          </p>
        </div>
      )}

      {records.games > 0 && (
        <p className="muted small">
          On this browser: {records.games} game{records.games === 1 ? '' : 's'}, robot trapped {records.traps} time
          {records.traps === 1 ? '' : 's'}, most replans forced {records.maxReplans}.
        </p>
      )}
    </section>
  );
}
