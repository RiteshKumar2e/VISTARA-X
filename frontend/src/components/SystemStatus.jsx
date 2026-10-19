const STATE_TEXT = {
  ok: 'Operational',
  degraded: 'Degraded',
  down: 'Unavailable',
  pending: 'Checking',
};

function Item({ name, state, detail }) {
  return (
    <li className={`sys sys-${state}`}>
      <span className="sys-mark" aria-hidden="true" />
      <span className="sys-name">{name}</span>
      <span className="sys-state">{STATE_TEXT[state]}</span>
      {detail && <span className="sys-detail">{detail}</span>}
    </li>
  );
}

export function SystemStatus({ backend, connection, telemetry }) {
  const st = backend.status;
  const backendState = backend.state === 'checking' ? 'pending' : backend.state === 'ok' ? 'ok' : 'down';
  const simState = backend.state !== 'ok' ? 'down' : st?.simulation?.running ? 'ok' : 'down';
  const wsState = { open: 'ok', stale: 'degraded', connecting: 'pending', closed: 'down' }[connection];
  const perception = st?.perception;
  let perState = 'pending';
  let perDetail = '';
  if (backend.state === 'down') perState = 'down';
  else if (perception) {
    if (perception.enabled === false) {
      perState = 'degraded';
      perDetail = 'Frame processing paused';
    } else if (perception.mode === 'yolov8') {
      perState = perception.last_error ? 'degraded' : 'ok';
      perDetail = 'YOLOv8 inference active';
    } else {
      perState = 'degraded';
      perDetail = perception.yolo_available
        ? 'Simulated detector active; YOLOv8 available'
        : `Simulated fallback; YOLOv8 ${perception.yolo_status}`;
    }
  }

  // Planner and controller states come from /status and live telemetry, not from page load.
  let plannerState = 'pending';
  let plannerDetail = '';
  let controllerState = 'pending';
  let controllerDetail = '';
  if (backend.state === 'down' || !st?.simulation?.running) {
    if (backend.state !== 'checking') {
      plannerState = 'down';
      controllerState = 'down';
    }
  } else {
    const lp = telemetry?.last_plan ?? st.planner?.last_plan;
    plannerState = lp && !lp.success ? 'degraded' : 'ok';
    plannerDetail = !lp
      ? 'A* ready; no route planned yet'
      : lp.success
        ? `last route ${lp.length.toFixed(1)} m in ${lp.planning_ms.toFixed(1)} ms`
        : `last plan failed: ${lp.reason.replace('_', ' ')}`;
    const status = telemetry?.mission?.status ?? st.mission?.status;
    controllerState = 'ok';
    controllerDetail =
      status === 'navigating'
        ? `driving at ${telemetry ? telemetry.robot.v.toFixed(2) : '?'} m/s`
        : status === 'paused'
          ? 'paused, holding position'
          : 'idle, robot stationary';
  }

  return (
    <section className="panel system" aria-labelledby="system-title">
      <div className="panel-head">
        <h2 id="system-title">System status</h2>
      </div>
      <ul className="sys-list">
        <Item name="Backend API" state={backendState} detail={backend.state === 'ok' ? `up ${Math.round(st.uptime_s)} s` : ''} />
        <Item
          name="Simulation"
          state={simState}
          detail={
            st?.simulation
              ? `${st.simulation.rate_hz} Hz, ${st.simulation.scenario}, ${
                  st.simulation.physics === 'pybullet' ? 'PyBullet collision checks' : 'analytic collision (PyBullet not installed)'
                }`
              : ''
          }
        />
        <Item
          name="Telemetry stream"
          state={wsState}
          detail={connection === 'stale' ? 'no updates for 3 s' : connection === 'closed' ? 'reconnecting' : ''}
        />
        <Item
          name="Navigation planner"
          state={plannerState}
          detail={plannerDetail}
        />
        <Item name="Robot controller" state={controllerState} detail={controllerDetail} />
        <Item name="Vision detector" state={perState} detail={perDetail} />
      </ul>
    </section>
  );
}
