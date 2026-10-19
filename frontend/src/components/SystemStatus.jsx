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

export function SystemStatus({ backend, connection }) {
  const st = backend.status;
  const backendState = backend.state === 'checking' ? 'pending' : backend.state === 'ok' ? 'ok' : 'down';
  const simState = backend.state !== 'ok' ? 'down' : st?.simulation?.running ? 'ok' : 'down';
  const wsState = { open: 'ok', stale: 'degraded', connecting: 'pending', closed: 'down' }[connection];
  const perception = st?.perception;
  let perState = 'pending';
  let perDetail = '';
  if (backend.state === 'down') perState = 'down';
  else if (perception) {
    if (perception.mode === 'yolov8') {
      perState = perception.last_error ? 'degraded' : 'ok';
      perDetail = 'YOLOv8 inference active';
    } else {
      perState = 'degraded';
      perDetail = perception.yolo_available
        ? 'Simulated detector active; YOLOv8 available'
        : `Simulated fallback; YOLOv8 ${perception.yolo_status}`;
    }
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
          detail={st?.simulation ? `${st.simulation.rate_hz} Hz, ${st.simulation.scenario}` : ''}
        />
        <Item
          name="Telemetry stream"
          state={wsState}
          detail={connection === 'stale' ? 'no updates for 3 s' : connection === 'closed' ? 'reconnecting' : ''}
        />
        <Item name="Perception" state={perState} detail={perDetail} />
      </ul>
    </section>
  );
}
