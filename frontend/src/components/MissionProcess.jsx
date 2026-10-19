import { useState } from 'react';
import { MISSION_PROCESS } from '../content/deck';

/** Interactive version of the deck's "Autonomous Navigation Mission Process" diagram. */
export function MissionProcess() {
  const [active, setActive] = useState('05');
  const step = MISSION_PROCESS.find((s) => s.id === active);

  return (
    <div className="process">
      <ol className="process-steps">
        {MISSION_PROCESS.map((s) => (
          <li key={s.id} className={s.decision ? 'decision' : ''}>
            <button
              type="button"
              className={`process-step${active === s.id ? ' selected' : ''}`}
              aria-pressed={active === s.id}
              aria-controls="process-detail"
              onClick={() => setActive(s.id)}
            >
              <span className="mono process-id">{s.id}</span>
              <span className="process-title">{s.title}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="process-branches muted small">
        At step 05: <strong>yes</strong> leads to 06 (replan) and back to 04; <strong>no</strong> continues to 07.
      </p>
      <div id="process-detail" className="process-detail" aria-live="polite">
        <p className="process-detail-head">
          <span className="mono">{step.id}</span> {step.title}
        </p>
        <p>{step.text}</p>
        <p className="muted">
          <strong>In VISTARA-X:</strong> {step.how}
        </p>
      </div>
    </div>
  );
}
