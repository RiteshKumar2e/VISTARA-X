import { memo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

const LEVEL = {
  info: 'Info',
  success: 'OK',
  warning: 'Warn',
  error: 'Error',
};

const MAX_SHOWN = 40;

const lastId = (list) => (list?.length ? list[list.length - 1].id : null);

/** Backend mission events merged with frontend-observed connection events, newest first.
 *  Re-renders only when the event lists change, not on every telemetry message. */
export const EventLog = memo(
  function EventLog({ events: backendEvents, localEvents = [] }) {
  const events = [...(backendEvents || []), ...localEvents]
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0))
    .slice(0, MAX_SHOWN);
  return (
    <section className="panel events" aria-labelledby="events-title">
      <div className="panel-head">
        <h2 id="events-title">Event log</h2>
        <span className="muted small">{events.length} recent</span>
      </div>
      {events.length ? (
        <ol className="event-list" role="log" aria-live="off">
          <AnimatePresence initial={false}>
            {events.map((e) => (
              <motion.li
                key={e.id}
                className={`event event-${e.level}${e.local ? ' event-local' : ''}`}
                initial={{ opacity: 0, backgroundColor: 'rgba(15, 110, 106, 0.12)' }}
                animate={{ opacity: 1, backgroundColor: 'rgba(15, 110, 106, 0)' }}
                transition={{ duration: 0.8 }}
              >
              <span className="event-level">{LEVEL[e.level] || e.level}</span>
              <time className="mono event-time" dateTime={e.timestamp} title={new Date(e.timestamp).toLocaleString()}>
                {e.local ? 'client' : `${e.sim_time.toFixed(1)} s`}
              </time>
              <span className="event-msg">{e.message}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      ) : (
        <p className="empty">No events yet. Selecting a target or starting a mission will appear here.</p>
      )}
    </section>
  );
  },
  (a, b) =>
    lastId(a.events) === lastId(b.events) &&
    a.events?.length === b.events?.length &&
    a.localEvents === b.localEvents,
);
