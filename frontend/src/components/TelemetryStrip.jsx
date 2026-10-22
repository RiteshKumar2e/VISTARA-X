import { missionLabel } from './StatusBadge';

const LINK = { open: ['ok', 'Live'], stale: ['warn', 'Delayed'], connecting: ['warn', 'Connecting'], closed: ['bad', 'Offline'] };

function Cell({ label, value, unit, tone, wide }) {
  return (
    <div className={`ts-cell${tone ? ` ts-${tone}` : ''}${wide ? ' ts-wide' : ''}`}>
      <dt>{label}</dt>
      <dd className="mono">
        {value}
        {unit && value !== 'unavailable' ? <span className="ts-unit">{unit}</span> : null}
      </dd>
    </div>
  );
}

/** Dense one-row readout of live robot state. Every value comes from the telemetry stream. */
export function TelemetryStrip({ telemetry, connection }) {
  const [linkTone, linkText] = LINK[connection] || LINK.connecting;
  if (!telemetry) {
    return (
      <dl className="telemetry-strip" aria-label="Live telemetry">
        <Cell label="Link" value={linkText} tone={linkTone} />
        <Cell label="Robot" value="unavailable" wide />
      </dl>
    );
  }
  const r = telemetry.robot;
  const m = telemetry.mission;
  const moving = telemetry.obstacles.filter((o) => o.moving).length;
  const pathOk = telemetry.path?.length >= 2;
  const route = !telemetry.target
    ? 'no destination'
    : pathOk
      ? `${telemetry.remaining_path_length != null ? telemetry.remaining_path_length.toFixed(1) : '—'} m left`
      : m.status === 'blocked'
        ? 'no valid route'
        : 'not planned';
  return (
    <dl className="telemetry-strip" aria-label="Live telemetry">
      <Cell label="Link" value={linkText} tone={linkTone} />
      <Cell label="State" value={`${missionLabel(m.status)}${m.waiting ? ' (waiting)' : ''}`} />
      <Cell label="Position" value={`${r.x.toFixed(2)}, ${r.y.toFixed(2)}`} unit=" m" />
      <Cell label="Heading" value={r.heading_deg.toFixed(0)} unit="°" />
      <Cell label="Speed" value={Math.abs(r.v).toFixed(2)} unit=" m/s" />
      <Cell label="Route" value={route} tone={m.status === 'blocked' && !m.waiting ? 'bad' : undefined} />
      <Cell label="Obstacles" value={`${telemetry.obstacles.length} (${moving} moving)`} />
      <Cell
        label="Clearance"
        value={telemetry.safety.clearance.toFixed(2)}
        unit=" m"
        tone={telemetry.safety.collisions > 0 ? 'bad' : telemetry.safety.warning ? 'warn' : undefined}
      />
      <Cell label="Sim time" value={telemetry.sim_time.toFixed(1)} unit=" s" />
    </dl>
  );
}
