import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { EventLog } from '../components/EventLog';
import { GuidedDemo } from '../components/GuidedDemo';
import { MissionControls } from '../components/MissionControls';
import { PerceptionPanel } from '../components/PerceptionPanel';
import { SimulationViewport } from '../components/SimulationViewport';
import { SystemStatus } from '../components/SystemStatus';
import { TelemetryPanel } from '../components/TelemetryPanel';
import { Toaster } from '../components/Toaster';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useCommand } from '../hooks/useCommand';
import { usePageMeta } from '../hooks/usePageMeta';
import { useTelemetry } from '../hooks/useTelemetry';
import { API_BASE_URL, api } from '../services/api';

const DEFAULT_WORLD = { width: 20, height: 12 };
const MAX_LOCAL_EVENTS = 40;

/** Hit-test an operator-added obstacle at a world point. */
function addedObstacleAt(telemetry, { x, y }) {
  return telemetry?.obstacles.find((o) => {
    if (!o.id.startsWith('user-')) return false;
    if (o.shape === 'circle') return Math.hypot(o.x - x, o.y - y) <= o.r + 0.15;
    return Math.abs(o.x - x) <= o.w / 2 + 0.15 && Math.abs(o.y - y) <= o.h / 2 + 0.15;
  });
}

/** Frontend-observed connection changes, merged into the event timeline. */
function useConnectionEvents(connection, backendState) {
  const [events, setEvents] = useState([]);
  const prev = useRef({ connection: null, backend: null });
  const nextId = useRef(1);
  useEffect(() => {
    const add = (level, message) =>
      setEvents((list) =>
        [...list, { id: `local-${nextId.current++}`, level, type: 'connection', message, timestamp: new Date().toISOString(), local: true }].slice(
          -MAX_LOCAL_EVENTS,
        ),
      );
    const p = prev.current;
    if (p.connection && p.connection !== connection) {
      if (connection === 'closed') add('error', 'Telemetry WebSocket disconnected; reconnecting');
      else if (connection === 'stale') add('warning', 'Telemetry stream stalled (no update for 3 s)');
      else if (connection === 'open' && (p.connection === 'closed' || p.connection === 'stale'))
        add('success', 'Telemetry WebSocket connection restored');
    }
    if (p.backend && p.backend !== backendState) {
      if (backendState === 'down') add('error', 'Backend API unreachable');
      else if (backendState === 'ok' && p.backend === 'down') add('success', 'Backend API reachable again');
    }
    prev.current = { connection, backend: backendState };
  }, [connection, backendState]);
  return events;
}

export default function Dashboard() {
  usePageMeta(
    'Live Mission | VISTARA-X Mission Console',
    'Run a live autonomous navigation mission: select a target, watch A* planning, drop an obstacle and see the robot replan.',
  );
  const { telemetry, connection, versionMismatch } = useTelemetry();
  const backend = useBackendStatus();
  const command = useCommand();
  const [world, setWorld] = useState(DEFAULT_WORLD);
  const [scenarios, setScenarios] = useState([]);
  const [clickMode, setClickMode] = useState('target');
  const [selectedObstacle, setSelectedObstacle] = useState(null);
  const [rejected, setRejected] = useState(null);
  const [demoSignal, setDemoSignal] = useState(0);
  const online = backend.state === 'ok' && connection !== 'closed';
  const localEvents = useConnectionEvents(connection, backend.state);

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

  // Drop a selection whose obstacle no longer exists (cleared or reset).
  useEffect(() => {
    if (selectedObstacle && telemetry && !telemetry.obstacles.some((o) => o.id === selectedObstacle)) {
      setSelectedObstacle(null);
    }
  }, [telemetry, selectedObstacle]);
  useEffect(() => {
    if (clickMode !== 'obstacle') setSelectedObstacle(null);
  }, [clickMode]);

  const reject = (p) => setRejected({ ...p, at: performance.now() });

  const onMapClick = async (p) => {
    if (!online) return;
    const { x, y } = p;
    const at = `(${x.toFixed(2)}, ${y.toFixed(2)})`;
    if (clickMode === 'obstacle') {
      const hit = addedObstacleAt(telemetry, p);
      if (hit) {
        setSelectedObstacle((s) => (s === hit.id ? null : hit.id));
        return;
      }
      if (selectedObstacle) {
        const ok = await command.run('map', () => api.moveObstacle(selectedObstacle, x, y), () => `Moved ${selectedObstacle} to ${at}`);
        if (ok) setSelectedObstacle(null);
        else reject(p);
        return;
      }
      const ok = await command.run('map', () => api.addObstacle(x, y), (r) => `Obstacle ${r.obstacle.id} placed at ${at}`);
      if (!ok) reject(p);
    } else {
      const ok = await command.run('map', () => api.setTarget(x, y), () => `Target set to ${at}`);
      if (!ok) reject(p);
    }
  };

  return (
    <div className="console">
      <div className="console-intro">
        <div>
          <h1>Live mission</h1>
          <p className="muted">
            Every value on this page comes from the running backend simulation. Select a target, start the mission, then drop an
            obstacle on the route to watch it replan. New here? Use the <a href="#demo-title">guided demo</a> or read{' '}
            <Link to="/architecture">how it works</Link>.
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

      <div className="console-grid">
        <div className="col-main">
          <SimulationViewport
            telemetry={telemetry}
            world={world}
            clickMode={clickMode}
            onMapClick={onMapClick}
            connection={connection}
            online={online}
            rejected={rejected}
            selectedObstacle={selectedObstacle}
          />
          <div className="split">
            <TelemetryPanel telemetry={telemetry} connection={connection} />
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
            onRestartDemo={() => setDemoSignal((n) => n + 1)}
          />
          <GuidedDemo telemetry={telemetry} command={command} online={online} startSignal={demoSignal} />
          <SystemStatus backend={backend} connection={connection} telemetry={telemetry} />
          <EventLog telemetry={telemetry} localEvents={localEvents} />
        </div>
      </div>
      <Toaster telemetry={telemetry} />
    </div>
  );
}
