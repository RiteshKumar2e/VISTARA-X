import { Link } from 'react-router-dom';
import { ArchitectureExplorer } from '../components/ArchitectureExplorer';
import { StatusTag } from '../components/StatusTag';
import { DATA_FLOW, DATA_FLOW_LOOP, INTERFACES } from '../content/deck';
import { usePageMeta } from '../hooks/usePageMeta';
import { useTelemetry } from '../hooks/useTelemetry';

const EXPLAINERS = [
  {
    title: 'Occupancy grid',
    short: 'The map is divided into 0.2 m cells, each marked free or blocked.',
    long: [
      'Obstacle geometry is rasterised into a 100 by 60 grid. Each obstacle is then inflated by the robot radius (0.30 m) plus the safety margin, so the planner can treat the robot as a single point: any cell whose centre is closer than that to an obstacle is blocked.',
      'A softer caution band just outside the inflated zone is traversable but costs more, so routes keep extra clearance where the space allows. GET /map also reports which free cells the camera has actually observed; never-seen cells are shown as unknown.',
    ],
  },
  {
    title: 'A* path planning',
    short: 'A best-first search that is guaranteed to find the cheapest route when one exists.',
    long: [
      'A* expands grid cells in order of cost-so-far plus an estimate of the remaining cost. We use the octile distance, which never overestimates on an 8-connected grid, so the result is optimal for the grid costs.',
      'Diagonal moves are only allowed when both neighbouring straight cells are free, so the route never squeezes past an obstacle corner. The raw cell path is then shortened with line-of-sight checks into a few waypoints. If the open set empties without reaching the target, the planner reports that no route exists.',
    ],
  },
  {
    title: 'Pure-pursuit control',
    short: 'The robot steers toward a point a fixed distance ahead on the route.',
    long: [
      'Each 50 ms tick the controller finds the closest point on the route, looks 0.7 m further along it, and turns toward that point. Speed falls when the heading error is large, the robot turns in place for sharp corners, and it slows down within 1.2 m of the goal.',
      'Speed, turn rate and acceleration are limited. A separate safety layer vetoes any step that would reduce the clearance to an obstacle below 5 cm.',
    ],
  },
  {
    title: 'Dynamic replanning',
    short: 'When something blocks the route ahead, a new route is planned from where the robot is.',
    long: [
      'Every tick, the next 4 m of the planned route is sampled against the live occupancy grid. If any sample lands in a blocked cell (for example because a barrier was dropped or the patrolling person walked into the aisle), A* runs again from the current pose.',
      'If no route exists and nothing is moving, the robot stops and the mission ends as Blocked. If a moving obstacle may clear the way, the robot waits and retries every second for up to 8 seconds before giving up. Success is never reported unless the robot is within 0.2 m of the target.',
    ],
  },
  {
    title: 'Perception and scene understanding',
    short: 'The camera image is turned into detections, ranges and tracked obstacles.',
    long: [
      'A forward camera is rendered from the robot pose. The active detector, either YOLOv8 or the labelled ground-truth detector, produces boxes; their range comes from the depth image. A class policy decides which classes are navigation-relevant (people, pallets, shelves) and which to ignore.',
      'Relevant detections are projected into world coordinates and associated over time into tracks, which go stale and expire when they are not seen again. A person within 2.5 m straight ahead halves the speed limit. Collision safety itself uses simulator geometry, not these estimates.',
    ],
  },
];

export default function Architecture() {
  usePageMeta(
    'System Architecture | VISTARA-X',
    'Interactive architecture of VISTARA-X: perception, decision and navigation, and control layers, with live backend status for each stage.',
  );
  const { telemetry, connection } = useTelemetry();

  return (
    <div className="content-page">
      <header className="page-hero">
        <p className="eyebrow">System architecture</p>
        <h1>Perception, planning, action, and continuous replanning</h1>
        <p className="lede">
          Select a stage to see what it does, its inputs and outputs, how it is implemented, and its live state in the running
          backend. Status labels show what is implemented, simulation-only, running with a fallback, or planned.
        </p>
      </header>

      <ArchitectureExplorer telemetry={telemetry} connection={connection} />

      <section className="section" aria-labelledby="flow-h">
        <h2 id="flow-h">Data flow</h2>
        <ol className="flow">
          {DATA_FLOW.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        <p className="muted">
          <span aria-hidden="true">&#8634;</span> {DATA_FLOW_LOOP}
        </p>
      </section>

      <section className="section" aria-labelledby="algo-h">
        <h2 id="algo-h">How the algorithms work</h2>
        <div className="explainers">
          {EXPLAINERS.map((e) => (
            <details className="explain" key={e.title}>
              <summary>
                <strong>{e.title}</strong>
                <span className="muted"> {e.short}</span>
              </summary>
              {e.long.map((para) => (
                <p key={para.slice(0, 24)}>{para}</p>
              ))}
            </details>
          ))}
        </div>
      </section>

      <section className="section" aria-labelledby="api-h">
        <h2 id="api-h">APIs and interfaces</h2>
        <div className="table-wrap">
          <table className="data data-lg">
            <thead>
              <tr>
                <th scope="col">Interface</th>
                <th scope="col">Planned in the deck</th>
                <th scope="col">Status</th>
                <th scope="col">In this prototype</th>
              </tr>
            </thead>
            <tbody>
              {INTERFACES.map((i) => (
                <tr key={i.name}>
                  <th scope="row">{i.name}</th>
                  <td>{i.deck}</td>
                  <td>
                    <StatusTag status={i.status} />
                  </td>
                  <td>{i.actual}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section" aria-labelledby="orig-h">
        <h2 id="orig-h">Original architecture diagram</h2>
        <p className="muted small">
          Static image from the team&rsquo;s deck, shown for reference. The interactive explorer above reflects the
          implementation, including which parts are fallbacks.
        </p>
        <img
          src="/deck/architecture-diagram.webp"
          width="1600"
          height="899"
          loading="lazy"
          decoding="async"
          className="deck-img"
          alt="Deck diagram, Autonomous Robot Navigation System. Perception layer: simulation or camera plus sensors, image processing with OpenCV, YOLO detection, scene understanding. Decision and navigation: target identification, decision engine, path planning with A* or Dijkstra, obstacle avoidance with dynamic replanning. Control and action: robot controller, robot movement, environment feedback, target reached, with a continuous replanning loop."
        />
        <p>
          <Link to="/technology">See the technology stack</Link>
        </p>
      </section>
    </div>
  );
}
