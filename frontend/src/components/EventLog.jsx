import { AnimatePresence, motion } from 'framer-motion';

const LEVEL = {
  info: 'Info',
  success: 'OK',
  warning: 'Warn',
  error: 'Error',
};

export function EventLog({ telemetry }) {
  const events = telemetry?.events ? [...telemetry.events].reverse() : [];
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
                className={`event event-${e.level}`}
                initial={{ opacity: 0, backgroundColor: 'rgba(15, 110, 106, 0.12)' }}
                animate={{ opacity: 1, backgroundColor: 'rgba(15, 110, 106, 0)' }}
                transition={{ duration: 0.8 }}
              >
              <span className="event-level">{LEVEL[e.level] || e.level}</span>
              <time className="mono event-time" dateTime={e.timestamp} title={new Date(e.timestamp).toLocaleString()}>
                {e.sim_time.toFixed(1)} s
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
}
