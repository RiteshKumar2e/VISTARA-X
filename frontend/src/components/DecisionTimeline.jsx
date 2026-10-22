import { memo } from 'react';

// Backend event types that describe the navigation loop, grouped by the stage of
// perceive -> predict -> decide -> navigate they belong to. Everything else stays in the full log.
const STAGE = {
  reset: ['setup', 'Scenario'],
  target: ['setup', 'Destination'],
  mission: ['setup', 'Mission'],
  planning: ['plan', 'Planning'],
  route_planned: ['plan', 'Route'],
  perception: ['perceive', 'Perception'],
  obstacle: ['perceive', 'Obstacle'],
  prediction: ['predict', 'Prediction'],
  obstruction: ['act', 'Obstruction'],
  replanned: ['plan', 'Replanned'],
  safety_stop: ['act', 'Safety stop'],
  collision_warning: ['act', 'Clearance'],
  blocked: ['outcome', 'Blocked'],
  goal_reached: ['outcome', 'Goal reached'],
  collision: ['outcome', 'Collision'],
  error: ['outcome', 'Error'],
};
const MAX_SHOWN = 14;

const lastId = (list) => (list?.length ? list[list.length - 1].id : null);

/** Explainable decision timeline: the latest navigation-loop events from the backend, newest first. */
export const DecisionTimeline = memo(
  function DecisionTimeline({ events }) {
    const items = (events || []).filter((e) => STAGE[e.type]).slice(-MAX_SHOWN).reverse();
    return (
      <section className="panel timeline" id="decisions" aria-labelledby="decisions-title">
        <div className="panel-head">
          <div>
            <p className="eyebrow">Explainable decisions</p>
            <h2 id="decisions-title">Decision timeline</h2>
          </div>
          <span className="muted small">simulation time</span>
        </div>
        {items.length ? (
          <ol className="tl-list" aria-live="off">
            {items.map((e) => {
              const [stage, label] = STAGE[e.type];
              return (
                <li key={e.id} className={`tl-item tl-${stage} tl-level-${e.level}`}>
                  <span className="tl-node" aria-hidden="true" />
                  <div className="tl-body">
                    <p className="tl-meta">
                      <span className="tl-kind">{label}</span>
                      <time className="mono" dateTime={e.timestamp}>
                        t = {e.sim_time.toFixed(1)} s
                      </time>
                    </p>
                    <p className="tl-msg">{e.message}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="empty">No navigation decisions yet. Select a destination and start a mission; each plan, prediction and response appears here.</p>
        )}
      </section>
    );
  },
  (a, b) => lastId(a.events) === lastId(b.events) && a.events?.length === b.events?.length,
);
