import { useEffect, useRef, useState } from 'react';
import { CheckIcon, CloseIcon, InfoIcon, WarningIcon } from './Icons';

// Events that deserve a prominent visual alert, with their severity and a short title.
const ALERTS = {
  obstruction: ['warning', 'Route blocked: robot stopped and replanning'],
  replanned: ['info', 'New route found'],
  blocked: ['danger', 'No safe route: robot stopped'],
  collision: ['danger', 'Collision'],
  collision_warning: ['warning', 'Very close to an obstacle'],
  safety_stop: ['warning', 'Safety stop'],
  error: ['danger', 'System error: robot halted'],
  goal_reached: ['success', 'Destination reached'],
  explore: ['info', 'Mapping'],
  prediction: ['warning', 'Predicted conflict'],
};
const ICON = { danger: WarningIcon, warning: WarningIcon, success: CheckIcon, info: InfoIcon };
const DURATIONS = [
  [5, '5 seconds'],
  [10, '10 seconds'],
  [30, '30 seconds'],
  [0, 'Until dismissed'],
];

function read(key, fallback) {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch {
    return fallback;
  }
}
function write(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* not remembered */
  }
}

/** Accessibility display settings, applied to <html> so every page follows them. */
export function useA11ySettings() {
  const [large, setLarge] = useState(() => read('vistara.a11y.large', '0') === '1');
  const [contrast, setContrast] = useState(() => read('vistara.a11y.contrast', '0') === '1');
  const [duration, setDuration] = useState(() => Number(read('vistara.a11y.alertSeconds', '10')));
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('a11y-large', large);
    root.classList.toggle('a11y-contrast', contrast);
    write('vistara.a11y.large', large ? '1' : '0');
    write('vistara.a11y.contrast', contrast ? '1' : '0');
    write('vistara.a11y.alertSeconds', String(duration));
  }, [large, contrast, duration]);
  const accessible = large && contrast && duration === 0;
  const setAccessible = (on) => {
    setLarge(on);
    setContrast(on);
    setDuration(on ? 0 : 10);
  };
  return { large, setLarge, contrast, setContrast, duration, setDuration, accessible, setAccessible };
}

export function AlertCentre({ telemetry, settings }) {
  const [alerts, setAlerts] = useState([]); // newest first
  const [now, setNow] = useState(() => Date.now());
  const seen = useRef(null);
  const events = telemetry?.events;

  useEffect(() => {
    if (!events) return;
    const ids = new Set(events.map((e) => e.id));
    if (seen.current === null) {
      seen.current = ids; // don't replay history on first load
      return;
    }
    // Routine changes (frontiers, predictive speed adjustments) stay in the event log and the
    // Prediction panel; only warnings and outcomes become banners.
    const fresh = events.filter(
      (e) =>
        !seen.current.has(e.id) &&
        ALERTS[e.type] &&
        (e.type !== 'explore' || e.level === 'success') &&
        (e.type !== 'prediction' || e.level === 'warning'),
    );
    seen.current = ids;
    if (!fresh.length) return;
    setAlerts((a) =>
      [
        ...fresh.reverse().map((e) => {
          const [level, title] =
            e.type === 'explore' && e.level === 'success'
              ? ['success', 'Mapping finished']
              : ALERTS[e.type];
          return { id: e.id, level, title, message: e.message, at: Date.now(), sim: e.sim_time };
        }),
        ...a,
      ].slice(0, 12),
    );
  }, [events]);

  // Reset clears the backend event log: forget what we saw.
  useEffect(() => {
    seen.current = null;
  }, [telemetry?.scenario]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const ttl = settings.duration * 1000;
  const visible = alerts.filter((a) => !a.dismissed && (ttl === 0 || now - a.at < ttl)).slice(0, 2);
  const dismiss = (id) => setAlerts((a) => a.map((x) => (x.id === id ? { ...x, dismissed: true } : x)));
  const status = telemetry?.mission?.status;
  const standing =
    status === 'blocked'
      ? ['danger', 'Robot is blocked', telemetry.mission.reason || 'No collision-free route exists']
      : status === 'error'
        ? ['danger', 'System error', telemetry.mission.reason]
        : null;

  return (
    <section className="alert-centre" aria-labelledby="alerts-title" id="alerts">
      <h2 id="alerts-title" className="sr-only">
        Alerts
      </h2>
      {standing && (
        <div className={`alert-banner alert-${standing[0]}`} role="alert">
          <WarningIcon size={22} />
          <div>
            <strong>{standing[1]}</strong>
            <p>{standing[2]}</p>
          </div>
        </div>
      )}
      {/* Transient alerts float over the page so they never shift the controls underneath. */}
      <div className="alert-float" aria-live="polite">
        {visible.map((a) => {
          const Icon = ICON[a.level];
          return (
            <div key={a.id} className={`alert-banner alert-${a.level}`} role={a.level === 'danger' ? 'alert' : 'status'}>
              <Icon size={22} />
              <div>
                <strong>{a.title}</strong>
                <p>
                  {a.message} <span className="mono small">t = {a.sim} s</span>
                </p>
              </div>
              <button type="button" className="icon-btn" onClick={() => dismiss(a.id)} aria-label={`Dismiss alert: ${a.title}`}>
                <CloseIcon size={16} />
              </button>
            </div>
          );
        })}
      </div>
      <details className="alert-settings">
        <summary>Display and alert settings{settings.accessible ? ' (accessible mode on)' : ''}</summary>
        <div className="alert-settings-body">
          <label className="check">
            <input type="checkbox" checked={settings.accessible} onChange={(e) => settings.setAccessible(e.target.checked)} />
            <strong>Accessible mode</strong>: large text, high contrast, alerts stay until dismissed
          </label>
          <label className="check">
            <input type="checkbox" checked={settings.large} onChange={(e) => settings.setLarge(e.target.checked)} />
            Large text
          </label>
          <label className="check">
            <input type="checkbox" checked={settings.contrast} onChange={(e) => settings.setContrast(e.target.checked)} />
            High contrast
          </label>
          <div className="field">
            <label htmlFor="alert-duration">Keep visual alerts for</label>
            <select id="alert-duration" value={settings.duration} onChange={(e) => settings.setDuration(Number(e.target.value))}>
              {DURATIONS.map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <p className="muted small">
            Every warning is shown as text with an icon; nothing important is signalled by sound or colour alone. Spoken robot responses
            are optional and always captioned in the command console.
          </p>
        </div>
      </details>
      {alerts.length > 0 && (
        <details className="alert-history">
          <summary>Recent alerts ({alerts.length})</summary>
          <ol>
            {alerts.map((a) => (
              <li key={a.id}>
                <span className={`alert-tag alert-tag-${a.level}`}>{a.level}</span> <strong>{a.title}</strong>: {a.message}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
