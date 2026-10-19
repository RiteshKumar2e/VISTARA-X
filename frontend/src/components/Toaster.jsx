import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { CloseIcon } from './Icons';

// Backend event types worth surfacing as notifications. Everything else stays in the log.
const NOTIFY = new Set(['replanned', 'goal_reached', 'blocked', 'collision', 'safety_stop']);
const AUTO_DISMISS_MS = 8000;
const MAX_TOASTS = 3;

/**
 * Dismissible notifications for mission events. Driven only by real backend
 * events from telemetry; events present before the page loaded are not replayed.
 */
export function Toaster({ telemetry }) {
  const [toasts, setToasts] = useState([]);
  const seen = useRef(null);
  const timers = useRef(new Map());

  useEffect(() => {
    const events = telemetry?.events;
    if (!events) return;
    if (seen.current === null) {
      seen.current = new Set(events.map((e) => e.id)); // ignore history on first load
      return;
    }
    const fresh = events.filter((e) => !seen.current.has(e.id));
    fresh.forEach((e) => seen.current.add(e.id));
    const wanted = fresh.filter((e) => NOTIFY.has(e.type));
    if (wanted.length) setToasts((t) => [...t, ...wanted].slice(-MAX_TOASTS));
  }, [telemetry?.events]);

  const dismiss = (id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((t) => t.filter((x) => x.id !== id));
  };

  useEffect(() => {
    toasts.forEach((t) => {
      if (!timers.current.has(t.id)) timers.current.set(t.id, setTimeout(() => dismiss(t.id), AUTO_DISMISS_MS));
    });
  }, [toasts]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  return (
    <div className="toaster" role="status" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            className={`toast toast-${t.level}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            <p>
              <strong>{t.type === 'goal_reached' ? 'Goal reached' : t.type === 'replanned' ? 'Route replanned' : t.type === 'blocked' ? 'Mission blocked' : t.type === 'collision' ? 'Collision' : 'Safety stop'}</strong>
              <span>{t.message}</span>
            </p>
            <button type="button" className="icon-btn" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
              <CloseIcon size={14} />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
