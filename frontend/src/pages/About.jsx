import { Link } from 'react-router-dom';
import { usePageMeta } from '../hooks/usePageMeta';

const PIPELINE = [
  ['Simulation sensors', 'Fixed 20 Hz simulation of a differential-drive robot. A forward camera is rendered by ray casting the scene.'],
  ['Perception', 'YOLOv8 inference on the camera frame when weights are present, or a clearly labelled ground-truth detector.'],
  ['Scene understanding', 'Detections are ranged with the camera depth buffer. A person within 2.5 m ahead halves the speed limit.'],
  ['Occupancy grid', '0.2 m cells from obstacle geometry, inflated by the robot radius plus a configurable safety margin.'],
  ['A* planning', '8-connected A* with an octile heuristic, no corner cutting, and line-of-sight smoothing into waypoints.'],
  ['Robot control', 'Pure-pursuit waypoint following with speed, turn-rate and acceleration limits.'],
  ['Collision monitoring', 'Every tick the next 4 m of route is checked against the live grid; a safety layer vetoes unsafe motion.'],
  ['Dynamic replanning', 'A blocked route triggers an immediate replan. With no route, the robot stops and reports Blocked.'],
  ['Live telemetry', 'A WebSocket streams authoritative state at 10 Hz to this dashboard.'],
];

export default function About() {
  usePageMeta(
    'How VISTARA-X Works | Perception, A* Planning and Replanning',
    'The VISTARA-X pipeline: simulated sensors, perception, occupancy-grid mapping, A* planning, control and dynamic replanning.',
  );
  return (
    <article className="prose-page">
      <header className="page-hero">
        <p className="eyebrow">VISTARA-X &middot; Team Hack01</p>
        <h1>Beyond seeing. Into understanding.</h1>
        <p className="lede">
          Autonomous robots must perceive their surroundings, recognise relevant objects and people, navigate toward an
          objective and avoid obstacles in real time. VISTARA-X is a simulation-first prototype of that loop.
        </p>
        <p>
          <Link className="btn btn-primary" to="/">
            Open the mission console
          </Link>
        </p>
      </header>

      <section aria-labelledby="mission-h">
        <h2 id="mission-h">The mission</h2>
        <p>
          <strong>Navigate to the target while avoiding obstacles.</strong> You choose a destination, the system plans a
          collision-aware route, and the robot drives it. When an obstacle appears on the route, the change is detected, the
          map is updated and a new route is planned. Success is reported only when the robot is within 0.2 m of the target;
          if no safe route exists, the robot stops and says so.
        </p>
      </section>

      <section aria-labelledby="pipeline-h">
        <h2 id="pipeline-h">Pipeline</h2>
        <ol className="pipeline">
          {PIPELINE.map(([title, text], i) => (
            <li key={title}>
              <span className="pipeline-num mono" aria-hidden="true">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="honesty-h">
        <h2 id="honesty-h">What is real, and what is simulated</h2>
        <ul>
          <li>
            Planning, control, collision checks and replanning run for real in the backend. The dashboard only displays what
            the backend computes.
          </li>
          <li>
            Collision avoidance uses ground-truth obstacle geometry from the simulator. The camera-derived detections are
            shown separately and are not used for safety decisions, apart from the person speed limit.
          </li>
          <li>
            The camera frame is a simple synthetic render. YOLOv8 (trained on real photographs) runs on it unmodified when
            enabled, and it may detect little. The default simulated detector is labelled as ground truth and reports no
            confidence score.
          </li>
          <li>The robot is a 2D kinematic model. Physics simulation (for example PyBullet) is future work.</li>
        </ul>
      </section>

      <section aria-labelledby="scope-h">
        <h2 id="scope-h">Implemented vs. future scope</h2>
        <div className="two-col">
          <div>
            <h3>Implemented</h3>
            <ul>
              <li>Deterministic scenarios with static, inserted and moving obstacles</li>
              <li>Occupancy grid, A* planning and path smoothing</li>
              <li>Pure-pursuit control with a safety stop layer</li>
              <li>Route-obstruction detection and replanning</li>
              <li>Honest Blocked state when no route exists</li>
              <li>Pluggable YOLOv8 or simulated detector</li>
              <li>REST API, WebSocket telemetry and automated tests</li>
            </ul>
          </div>
          <div>
            <h3>Future scope</h3>
            <ul>
              <li>Physics simulation and photorealistic camera rendering</li>
              <li>Mapping obstacles from perception instead of ground truth (SLAM)</li>
              <li>Trajectory prediction for moving people</li>
              <li>Deployment on physical robot hardware via ROS 2</li>
            </ul>
          </div>
        </div>
      </section>

      <section aria-labelledby="team-h">
        <h2 id="team-h">Team Hack01</h2>
        <ul className="team">
          <li>
            <strong>Ritesh Kumar</strong>
            <span>Backend, robotics logic and AI/ML</span>
          </li>
          <li>
            <strong>Kainat Afrazi</strong>
            <span>Frontend and user experience</span>
          </li>
        </ul>
      </section>
    </article>
  );
}
