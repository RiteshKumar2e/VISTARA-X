const MISSION = {
  idle: { label: 'Idle', tone: 'neutral' },
  planning: { label: 'Planning', tone: 'accent' },
  navigating: { label: 'Navigating', tone: 'accent' },
  replanning: { label: 'Replanning', tone: 'warning' },
  error: { label: 'Error', tone: 'danger' },
  paused: { label: 'Paused', tone: 'warning' },
  goal_reached: { label: 'Goal reached', tone: 'success' },
  blocked: { label: 'Blocked', tone: 'danger' },
  stopped: { label: 'Stopped', tone: 'neutral' },
};

/** Text label always present, so the state never relies on colour alone. */
export function MissionStatusBadge({ status, waiting }) {
  const s = MISSION[status] || { label: status || 'Unknown', tone: 'neutral' };
  return (
    <span className={`badge badge-${s.tone}`} data-status={status}>
      <span className="badge-mark" aria-hidden="true" />
      <span>
        <span className="sr-only">Mission status: </span>
        {s.label}
        {waiting ? ' (waiting)' : ''}
      </span>
    </span>
  );
}

export function Badge({ tone = 'neutral', children }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span className="badge-mark" aria-hidden="true" />
      <span>{children}</span>
    </span>
  );
}

export function missionLabel(status) {
  return MISSION[status]?.label || status;
}
