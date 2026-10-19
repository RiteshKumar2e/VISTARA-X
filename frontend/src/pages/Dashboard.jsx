import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { EventLog } from '../components/EventLog';
import { GuidedDemo } from '../components/GuidedDemo';
import { MissionControls } from '../components/MissionControls';
import { PerceptionPanel } from '../components/PerceptionPanel';
import { SimulationViewport } from '../components/SimulationViewport';
import { SystemStatus } from '../components/SystemStatus';
import { TelemetryPanel } from '../components/TelemetryPanel';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useCommand } from '../hooks/useCommand';
import { usePageMeta } from '../hooks/usePageMeta';
import { useTelemetry } from '../hooks/useTelemetry';
import { API_BASE_URL, api } from '../services/api';

const DEFAULT_WORLD = { width: 20, height: 12 };

export default function Dashboard() {
  usePageMeta(
    'VISTARA-X Mission Console | Vision-Based Autonomous Navigation',
    'Run a live autonomous navigation mission: select a target, watch A* planning, drop an obstacle and see the robot replan.',
  );
  const { telemetry, connection, versionMismatch } = useTelemetry();
  const backend = useBackendStatus();
  const command = useCommand();
  const [world, setWorld] = useState(DEFAULT_WORLD);
  const [scenarios, setScenarios] = useState([]);
  const [clickMode, setClickMode] = useState('target');
  const online = backend.state === 'ok' && connection !== 'closed';

  useEffect(() => {
    if (backend.state !== 'ok') return;
    let cancelled = false;
    Promise.all([api.map(), api.scenarios()])
      .then(([map, list]) => {
        if (cancelled) return;
        setWorld({ width: map.width, height: map.height });
        setScenarios(list.scenarios);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [backend.state]);

  const onMapClick = ({ x, y }) => {
    if (!online) return;
    if (clickMode === 'obstacle') {
      command.run('map', () => api.addObstacle(x, y), (r) => `Obstacle ${r.obstacle.id} placed at (${x.toFixed(2)}, ${y.toFixed(2)})`);
    } else {
      command.run('map', () => api.setTarget(x, y), () => `Target set to (${x.toFixed(2)}, ${y.toFixed(2)})`);
    }
  };

  return (
    <div className="console">
      <div className="console-intro">
        <div>
          <h1>Mission console</h1>
          <p className="muted">
            Beyond Seeing. Into Understanding. A simulated robot perceives its surroundings, plans with A* on an occupancy grid,
            and replans when obstacles appear. <Link to="/about">How it works</Link>
          </p>
        </div>
      </div>

      {backend.state === 'down' && (
        <div className="banner banner-error" role="alert">
          <div>
            <strong>Backend unreachable.</strong> The console cannot reach <span className="mono">{API_BASE_URL}</span>. Start the
            backend (see README) and this page reconnects automatically.
          </div>
          <button type="button" className="btn" onClick={backend.retry}>
            Retry now
          </button>
        </div>
      )}
      {versionMismatch && (
        <div className="banner banner-warning" role="status">
          The backend sends a different telemetry version than this dashboard expects. Update both apps together.
        </div>
      )}
      {backend.state === 'ok' && connection === 'stale' && (
        <div className="banner banner-warning" role="status">
          Telemetry has not updated for a few seconds. Values shown may be out of date.
        </div>
      )}

      <div className="console-grid">
        <div className="col-main">
          <SimulationViewport
            telemetry={telemetry}
            world={world}
            clickMode={clickMode}
            onMapClick={onMapClick}
            connection={connection}
            online={online}
          />
          <div className="split">
            <TelemetryPanel telemetry={telemetry} />
            <PerceptionPanel telemetry={telemetry} command={command} online={online} />
          </div>
        </div>
        <div className="col-side">
          <MissionControls
            telemetry={telemetry}
            command={command}
            online={online}
            scenarios={scenarios}
            world={world}
            clickMode={clickMode}
            setClickMode={setClickMode}
          />
          <GuidedDemo telemetry={telemetry} command={command} online={online} />
          <SystemStatus backend={backend} connection={connection} />
          <EventLog telemetry={telemetry} />
        </div>
      </div>
    </div>
  );
}
