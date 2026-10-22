import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCentre, useA11ySettings } from '../components/AlertCentre';
import { ChallengePanel } from '../components/ChallengePanel';
import { CommandConsole } from '../components/CommandConsole';
import { EvaluationPanel } from '../components/EvaluationPanel';
import { MappingPanel } from '../components/MappingPanel';
import { OperationsPanel } from '../components/OperationsPanel';
import { PredictionPanel } from '../components/PredictionPanel';
import { EventLog } from '../components/EventLog';
import { GuidedDemo } from '../components/GuidedDemo';
import { MissionControls } from '../components/MissionControls';
import { MissionOverview } from '../components/MissionOverview';
import { ModelsPanel } from '../components/ModelsPanel';
import { NavigationPanel } from '../components/NavigationPanel';
import { PerceptionPanel } from '../components/PerceptionPanel';
import { SensorsPanel } from '../components/SensorsPanel';
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
const DEMO_SPEED = 0.6; // m/s in demo mode: slow enough to follow, and to drop an obstacle in time

function readStored(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function store(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the preference is not remembered */
  }
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
  const [objectType, setObjectType] = useState('crate');
  const [walkStart, setWalkStart] = useState(null); // first click of a walking person's route
  const [lite, setLite] = useState(() => readStored('vistara.demoMode') === '1');
  const [challenge, setChallenge] = useState(null); // 'Trap the robot' game state
  const a11y = useA11ySettings();

  // Demo mode lowers 3D quality locally and the robot's max speed on the backend;
  // turning it off restores the speed that was set before.
  const toggleDemoMode = async (on) => {
    setLite(on);
    store('vistara.demoMode', on ? '1' : '0');
    if (!online) return;
    const current = telemetry?.params?.max_speed;
    if (on && current) store('vistara.speedBeforeDemo', String(current));
    const speed = on ? Math.min(DEMO_SPEED, current ?? DEMO_SPEED) : Number(readStored('vistara.speedBeforeDemo')) || 0.9;
    await command.run(
      'demo-mode',
      () => api.configure({ max_speed: speed }),
      () => (on ? `Demo mode on: reduced 3D quality, max speed ${speed.toFixed(1)} m/s` : `Demo mode off: max speed ${speed.toFixed(1)} m/s`),
    );
  };
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
    setWalkStart(null);
  }, [clickMode, objectType]);

  const reject = (p) => setRejected({ ...p, at: performance.now() });

  // A pick comes from either view: { point: {x, y} | null, obstacleId | null }.
  const onMapClick = async ({ point, obstacleId }) => {
    if (!online) return;
    if (clickMode === 'obstacle') {
      const inChallenge = challenge?.active;
      if (inChallenge && obstacleId?.startsWith('user-')) {
        // Barriers stay where they were placed during a challenge.
        await command.run('map', () => Promise.reject(new Error('Barriers cannot be moved during the challenge.')), null);
        return;
      }
      if (inChallenge && point && challenge.placed >= challenge.budget) {
        reject(point);
        await command.run('map', () => Promise.reject(new Error(`No barriers left: all ${challenge.budget} are placed.`)), null);
        return;
      }
      const counted = (ok) => {
        if (ok && inChallenge) setChallenge((c) => c && { ...c, placed: c.placed + 1 });
      };
      if (obstacleId?.startsWith('user-')) {
        setSelectedObstacle((s) => (s === obstacleId ? null : obstacleId));
        return;
      }
      if (!point) return;
      const at = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
      if (selectedObstacle) {
        const ok = await command.run('map', () => api.moveObstacle(selectedObstacle, point.x, point.y), () => `Moved ${selectedObstacle} to ${at}`);
        if (ok) setSelectedObstacle(null);
        else reject(point);
        return;
      }
      if (objectType === 'person-walking') {
        if (!walkStart) {
          setWalkStart(point); // wait for the second click: end of the walking route
          return;
        }
        const start = walkStart;
        setWalkStart(null);
        const ok = await command.run(
          'map',
          () => api.addObstacle(start.x, start.y, { label: 'person', patrol_to: point }),
          (r) => `Walking person ${r.obstacle.id} added between (${start.x.toFixed(2)}, ${start.y.toFixed(2)}) and ${at}`,
        );
        counted(ok);
        if (!ok) reject(point);
        return;
      }
      const opts = objectType === 'person' ? { label: 'person' } : objectType === 'cone' ? { label: 'cone', shape: 'circle', size: 0.6 } : { label: objectType };
      const ok = await command.run('map', () => api.addObstacle(point.x, point.y, opts), (r) => `Obstacle ${r.obstacle.id} placed at ${at}`);
      counted(ok);
      if (!ok) reject(point);
      return;
    }
    if (!point) return;
    const at = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    const ok = await command.run('map', () => api.setTarget(point.x, point.y), () => `Target set to ${at}`);
    if (!ok) reject(point);
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
      <MissionOverview
        telemetry={telemetry}
        backend={backend}
        connection={connection}
        command={command}
        online={online}
        demoMode={lite}
        onDemoMode={toggleDemoMode}
      />
      <AlertCentre telemetry={telemetry} settings={a11y} />

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
            setClickMode={setClickMode}
            objectType={objectType}
            setObjectType={setObjectType}
            walkStart={walkStart}
            onMapClick={onMapClick}
            connection={connection}
            online={online}
            rejected={rejected}
            selectedObstacle={selectedObstacle}
            lite={lite}
          />
          <OperationsPanel telemetry={telemetry} online={online} command={command} />
          <PredictionPanel telemetry={telemetry} online={online} command={command} />
          <MappingPanel telemetry={telemetry} online={online} command={command} />
          <div className="split">
            <TelemetryPanel telemetry={telemetry} connection={connection} />
            <PerceptionPanel telemetry={telemetry} command={command} online={online} />
          </div>
          <div className="split">
            <SensorsPanel telemetry={telemetry} command={command} online={online} />
            <NavigationPanel telemetry={telemetry} online={online} />
          </div>
          <EvaluationPanel online={online} />
          <div className="split">
            <ModelsPanel telemetry={telemetry} command={command} online={online} />
          </div>
        </div>
        <div className="col-side">
          <CommandConsole telemetry={telemetry} online={online} command={command} />
          <MissionControls
            telemetry={telemetry}
            command={command}
            online={online}
            scenarios={scenarios}
            world={world}
            clickMode={clickMode}
            setClickMode={setClickMode}
            onRestartDemo={() => setDemoSignal((n) => n + 1)}
            selectedObstacle={selectedObstacle}
            onRemoveObstacle={async () => {
              const id = selectedObstacle;
              const ok = await command.run('remove', () => api.removeObstacle(id), () => `Obstacle ${id} removed`);
              if (ok) setSelectedObstacle(null);
            }}
          />
          <ChallengePanel
            telemetry={telemetry}
            command={command}
            online={online}
            challenge={challenge}
            setChallenge={setChallenge}
            setClickMode={setClickMode}
            setObjectType={setObjectType}
          />
          <GuidedDemo telemetry={telemetry} command={command} online={online} startSignal={demoSignal} />
          <SystemStatus backend={backend} connection={connection} telemetry={telemetry} />
          <EventLog events={telemetry?.events} localEvents={localEvents} />
        </div>
      </div>
      <Toaster telemetry={telemetry} />
    </div>
  );
}
