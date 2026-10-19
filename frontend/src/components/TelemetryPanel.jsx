import { Term } from './Term';

// Values the backend did not supply are shown as "Unavailable", never estimated.
const fmt = (v, digits = 2, unit = '') =>
  v === null || v === undefined || Number.isNaN(v) ? 'Unavailable' : `${Number(v).toFixed(digits)}${unit}`;

function Row({ label, children, tone }) {
  return (
    <div className={`kv${tone ? ` kv-${tone}` : ''}`}>
      <dt>{label}</dt>
      <dd className="mono">{children}</dd>
    </div>
  );
}

/** Every value shown here is computed by the backend simulation; nothing is estimated client-side. */
export function TelemetryPanel({ telemetry }) {
  if (!telemetry) {
    return (
      <section className="panel" aria-labelledby="telemetry-title">
        <div className="panel-head">
          <h2 id="telemetry-title">Live telemetry</h2>
        </div>
        <p className="empty">No telemetry yet. It appears as soon as the simulation stream connects.</p>
      </section>
    );
  }
  const { robot: r, mission: m, safety: s, last_plan: plan, perception: p } = telemetry;
  const wp = telemetry.current_waypoint;
  const pathLen = telemetry.path.length;
  const progress = m.progress;

  return (
    <section className="panel" aria-labelledby="telemetry-title">
      <div className="panel-head">
        <h2 id="telemetry-title">Live telemetry</h2>
        <span className="muted small mono">seq {telemetry.seq}</span>
      </div>

      <div className="progress-block">
        <div className="progress-label">
          <Term tip="Distance travelled divided by distance travelled plus the remaining planned route. It changes when the route is replanned.">
            Navigation progress
          </Term>
          <span className="mono">{progress === null ? '—' : `${Math.round(progress * 100)}%`}</span>
        </div>
        <div
          className="progress"
          role="progressbar"
          aria-label="Navigation progress (distance travelled over travelled plus remaining route)"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress === null ? undefined : Math.round(progress * 100)}
        >
          <span style={{ width: `${(progress ?? 0) * 100}%` }} />
        </div>
      </div>

      <dl className="kv-grid status-grid">
        <Row label="Goal reached" tone={m.goal_reached ? 'success' : undefined}>
          {m.goal_reached ? 'yes' : 'no'}
        </Row>
        <Row label="Collision status" tone={s.in_contact || s.collisions ? 'danger' : s.warning ? 'warning' : undefined}>
          {s.in_contact ? 'in contact' : s.warning ? 'clearance warning' : 'clear'}
        </Row>
        <Row label="Detections">
          {p?.enabled ? `${p.detections.length} (${p.mode === 'yolov8' ? 'YOLOv8' : 'simulated'})` : 'perception off'}
        </Row>
        <Row label={<Term tip="Which geometry engine verifies clearance and contact every tick: PyBullet when installed, otherwise an exact 2D distance calculation.">Physics check</Term>}>{s.physics === 'pybullet' ? 'PyBullet' : 'analytic 2D'}</Row>
      </dl>

      <h3 className="sub">Robot</h3>
      <dl className="kv-grid">
        <Row label="Position">
          x {fmt(r.x)} / y {fmt(r.y)} m
        </Row>
        <Row label={<Term tip="Degrees, measured counter-clockwise from the +x axis (pointing right on the map).">Heading (deg)</Term>}>
          {fmt(r.heading_deg, 1, '\u00b0')}
        </Row>
        <Row label="Linear speed">{fmt(r.v, 2, ' m/s')}</Row>
        <Row label="Turn rate">{fmt(r.w, 2, ' rad/s')}</Row>
      </dl>

      <h3 className="sub">Mission</h3>
      <dl className="kv-grid">
        <Row label="Target">{telemetry.target ? `x ${fmt(telemetry.target.x)} / y ${fmt(telemetry.target.y)} m` : 'none'}</Row>
        <Row label="Distance to target">{fmt(telemetry.distance_to_target, 2, ' m')}</Row>
        <Row label="Route length (planned)">{plan?.success ? fmt(plan.length, 2, ' m') : 'Unavailable'}</Row>
        <Row label="Route remaining">{fmt(telemetry.remaining_path_length, 2, ' m')}</Row>
        <Row label={<Term tip="The smoothed A* route is a list of waypoints. The controller is currently steering toward this one.">Waypoint</Term>}>
          {wp ? `${wp.index} of ${pathLen - 1} (x ${fmt(wp.x, 1)}, y ${fmt(wp.y, 1)})` : pathLen ? 'final' : 'no route'}
        </Row>
        <Row label="Mission time">{fmt(m.elapsed, 1, ' s')}</Row>
        <Row label="Distance travelled">{fmt(m.distance_travelled, 2, ' m')}</Row>
        <Row label={<Term tip="How many times this mission computed a new A* route because the current one became blocked.">Replans</Term>}>{m.replans}</Row>
        {m.reason && <Row label="Status detail">{m.reason}</Row>}
      </dl>

      <h3 className="sub">Safety</h3>
      <dl className="kv-grid">
        <Row label={<Term tip="Gap between the robot's outer edge and the nearest obstacle or wall surface. A warning appears below 0.10 m.">Clearance</Term>} tone={s.warning ? 'danger' : undefined}>
          {fmt(Math.max(s.clearance, 0), 2, ' m')} {s.nearest ? `to ${s.nearest}` : ''}
          {s.warning ? ' (warning)' : ''}
        </Row>
        <Row label={<Term tip="Robot radius plus safety margin. The planner treats every cell closer than this to an obstacle as blocked.">Planner inflation</Term>}>{fmt(s.inflation, 2, ' m')}</Row>
        <Row label={<Term tip="Times the safety layer vetoed a motion step that would have brought the robot within 5 cm of an obstacle.">Safety stops</Term>}>{m.safety_stops}</Row>
        <Row label="Collisions" tone={s.collisions ? 'danger' : undefined}>
          {s.collisions}
        </Row>
      </dl>

      <h3 className="sub">Last A* plan</h3>
      {plan ? (
        plan.success ? (
          <dl className="kv-grid">
            <Row label="Length">{fmt(plan.length, 2, ' m')}</Row>
            <Row label="Waypoints">{plan.waypoints}</Row>
            <Row label={<Term tip="Grid cells A* had to examine before finding the route. Fewer means an easier search.">Nodes expanded</Term>}>{plan.expanded}</Row>
            <Row label="Planning time">{fmt(plan.planning_ms, 1, ' ms')}</Row>
          </dl>
        ) : (
          <p className="feedback-msg feedback-error">No route found ({plan.reason.replace('_', ' ')}).</p>
        )
      ) : (
        <p className="empty">No route planned yet. Start a mission to run A*.</p>
      )}
    </section>
  );
}
