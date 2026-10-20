// All content derived from the original pitch deck "Hack01_Hack in Hills '26.pptx"
// (8 slides), rewritten as website copy. Each block notes its source slide so the
// content inventory in docs/CONTENT_INVENTORY.md can be checked against it.
//
// Implementation status vocabulary used across the site:
//   implemented  - runs in this prototype
//   simulation   - runs, but only against the simulator (no real hardware/sensors)
//   fallback     - a labelled stand-in is used when the real component is unavailable
//   partial      - part of the deck's description is implemented

export const STATUS = {
  implemented: { label: 'Implemented', tone: 'success' },
  simulation: { label: 'Simulation only', tone: 'accent' },
  fallback: { label: 'With labelled fallback', tone: 'warning' },
  partial: { label: 'Partially implemented', tone: 'warning' },
};

// Slide 1: Team
export const TEAM = {
  name: 'Hack01',
  event: "Hack in Hills '26",
  members: [
    { name: 'Ritesh Kumar', role: 'Backend and AI/ML Developer' },
    { name: 'Kainat Afrazi', role: 'Frontend Developer' },
  ],
};

// Slide 2: Problem statement and theme
export const PROBLEM = {
  title: 'Vision-Based Autonomous Robot',
  statement:
    'Autonomous robots need to understand their surroundings, identify relevant objects and people, navigate toward a given objective, and avoid obstacles in real time.',
  challenge: [
    'Perceive the environment through AI-powered vision',
    'Detect relevant objects and obstacles',
    'Understand the scene',
    'Navigate autonomously toward a target',
    'React to changing obstacles in real time',
  ],
  theme: ['AI', 'Computer Vision', 'Autonomous Navigation', 'Real-Time Decision Making'],
};

// Slide 3: Solution
export const SOLUTION = {
  summary:
    'A simulation-first autonomous robot system that combines computer vision, scene understanding and navigation to reach a specified objective safely.',
  overview: [
    'Observe the environment',
    'Detect objects, the target and obstacles',
    'Understand the scene',
    'Generate a navigation path',
    'Navigate toward the objective',
    'Detect obstacles dynamically',
    'Replan and continue safely',
  ],
  features: [
    {
      title: 'AI-based object and obstacle detection',
      status: 'fallback',
      note: 'YOLOv8 runs on the simulated camera when weights are present; a ground-truth detector is the labelled default.',
    },
    {
      title: 'Target identification',
      status: 'implemented',
      note: 'The operator selects the target on the map or by coordinates; it is validated against obstacle safety zones.',
    },
    { title: 'Autonomous path planning', status: 'implemented', note: 'A* search on an inflated occupancy grid.' },
    {
      title: 'Dynamic obstacle avoidance',
      status: 'simulation',
      note: 'Route checks every tick plus a safety-stop layer, verified against PyBullet collision geometry.',
    },
    {
      title: 'Real-time path replanning',
      status: 'implemented',
      note: 'An obstructed route triggers a new A* plan; with no route the robot stops and reports Blocked.',
    },
    {
      title: 'Live navigation visualisation',
      status: 'implemented',
      note: 'The mission console renders live WebSocket telemetry from the backend.',
    },
  ],
  uniqueValue: 'Perception, decision and action in one continuous autonomous loop.',
};

// Slide 6: Mission and the "Autonomous Navigation Mission Process" diagram
export const MISSION = 'Navigate to the target while avoiding obstacles.';
export const MISSION_PROCESS = [
  {
    id: '01',
    title: 'Environment detected',
    text: 'The system scans the surrounding area.',
    how: 'The simulated forward camera renders the scene; detections and the explored-area map update several times per second.',
  },
  {
    id: '02',
    title: 'Target identified',
    text: 'The destination is located and locked.',
    how: 'You choose the target on the map or by coordinates; the backend validates it and locks it for the mission.',
  },
  {
    id: '03',
    title: 'Safe path generated',
    text: 'A route is calculated to the target.',
    how: 'A* searches the occupancy grid, inflated by the robot radius plus a safety margin, then smooths the result into waypoints.',
  },
  {
    id: '04',
    title: 'Robot starts autonomous navigation',
    text: 'The robot begins moving along the path.',
    how: 'A pure-pursuit controller turns the route into speed and turn-rate commands at a fixed 20 Hz.',
  },
  {
    id: '05',
    title: 'Obstacle detected?',
    text: 'Check whether an obstacle blocks the path.',
    how: 'Every tick, the next 4 m of route is checked against the live grid. Yes leads to step 06; no continues toward step 07.',
    decision: true,
  },
  {
    id: '06',
    title: 'Path automatically replanned',
    text: 'The system calculates a new route.',
    how: 'A new A* plan starts from the current pose and navigation resumes at step 04. If no route exists, the robot stops and reports Blocked.',
  },
  {
    id: '07',
    title: 'Target reached',
    text: 'The robot arrives at the destination.',
    how: 'Reported only when the robot centre is within 0.2 m of the target.',
  },
];

// Slide 4: Architecture diagram "Autonomous Robot Navigation System"
// (perception -> planning -> action -> continuous replanning)
export const ARCHITECTURE_LAYERS = [
  { id: 'perception', title: 'Perception layer' },
  { id: 'decision', title: 'Decision and navigation' },
  { id: 'control', title: 'Control and action' },
];

export const ARCHITECTURE = [
  {
    id: '1.1',
    layer: 'perception',
    title: 'Simulation / camera + sensors',
    deck: 'Visual and distance input',
    status: 'simulation',
    purpose: 'Produce what the robot would see: an RGB frame plus per-pixel distance.',
    inputs: 'Robot pose, scene geometry',
    outputs: 'RGB frame, depth image and segmentation mask; LiDAR scan; ultrasonic ranges; IMU and wheel-odometry readings',
    implementation:
      'All sensors are simulated against the scene geometry with seeded noise: a PyBullet TinyRenderer RGB/depth camera (70 degree field of view), a 2D LiDAR (configurable angle, resolution, range and rate), a six-channel ultrasonic ring, an IMU with gyro bias, and wheel odometry with slip. Each reports health, rate and data age.',
    modules: ['backend/app/simulation/physics.py', 'backend/app/perception/camera.py', 'backend/app/sensors/'],
    live: 'camera',
  },
  {
    id: '1.2',
    layer: 'perception',
    title: 'Image processing',
    deck: 'OpenCV preprocessing',
    status: 'partial',
    purpose: 'Prepare frames for detection and transport.',
    inputs: 'Raw RGB frame',
    outputs: 'JPEG frames for the dashboard; resized tensors for YOLOv8',
    implementation:
      'OpenCV encodes frames for the dashboard; Ultralytics performs YOLOv8 letterboxing and normalisation. No additional filtering stage is implemented.',
    modules: ['backend/app/perception/service.py'],
  },
  {
    id: '1.3',
    layer: 'perception',
    title: 'YOLO detection',
    deck: 'Objects and obstacles',
    status: 'fallback',
    purpose: 'Detect objects, obstacles and people in the camera frame.',
    inputs: 'Camera frame',
    outputs: 'Class labels, bounding boxes, confidence scores (YOLOv8) and range from the depth buffer',
    implementation:
      'A model registry discovers YOLO weight files and runs a primary model, with an optional secondary model in cascade or multi-model mode. Results are merged with class-aware NMS, tagged with model and frame id, and governed by a latency budget. The default is a simulated detector that projects ground-truth geometry; it is labelled as such and reports no confidence.',
    modules: ['backend/app/perception/registry.py', 'backend/app/perception/detectors.py'],
    live: 'detector',
  },
  {
    id: '1.4',
    layer: 'perception',
    title: 'Scene understanding',
    deck: 'Mapped environment state',
    status: 'implemented',
    purpose: 'Turn detections into navigation-relevant facts.',
    inputs: 'Detections, robot pose',
    outputs: 'Relevant vs ignored classes, nearest obstacle, person-ahead speed limit, obstacle tracks, explored-area map',
    implementation:
      'A configurable class policy decides which classes matter. Ranged detections are projected into the world and tracked; stale tracks expire. Camera rays mark observed cells, so the map distinguishes unknown space.',
    modules: ['backend/app/scene/'],
    live: 'scene',
  },
  {
    id: '2.1',
    layer: 'decision',
    title: 'Target identification',
    deck: 'Goal position and constraints',
    status: 'implemented',
    purpose: 'Fix the goal and check that it is reachable in principle.',
    inputs: 'Operator selection (map click or coordinates)',
    outputs: 'Validated target, or a clear rejection',
    implementation:
      'Targets must be inside the map and outside every static obstacle safety zone. The target is chosen by the operator, not inferred from vision.',
    modules: ['backend/app/simulation/engine.py'],
    live: 'target',
  },
  {
    id: '2.2',
    layer: 'decision',
    title: 'Decision engine',
    deck: 'Select next best action',
    status: 'implemented',
    purpose: 'Decide what the robot does next: plan, drive, replan, wait, stop or finish.',
    inputs: 'Mission state, route checks, safety checks, perception summary',
    outputs: 'Mission status: Idle, Planning, Navigating, Paused, Blocked, Stopped or Goal reached',
    implementation: 'A mission state machine running on the single simulation thread, so only one controller drives the robot.',
    modules: ['backend/app/simulation/engine.py'],
    live: 'mission',
  },
  {
    id: '2.2a',
    layer: 'decision',
    title: 'Occupancy grid',
    deck: 'Added for clarity: part of "mapped environment state" in the deck',
    status: 'implemented',
    purpose: 'Represent free, blocked and unknown space for the planner.',
    inputs: 'Obstacle geometry, robot radius, safety margin, camera observations',
    outputs: 'Inflated 100 x 60 grid (0.2 m cells) with a caution band; explored/unknown mask',
    implementation:
      'Obstacles are rasterised and inflated by the robot radius plus the safety margin. GET /map returns cell states: occupied, inflated, observed free and unknown.',
    modules: ['backend/app/navigation/grid.py', 'backend/app/scene/observation.py'],
    live: 'grid',
  },
  {
    id: '2.3',
    layer: 'decision',
    title: 'Path planning',
    deck: 'A* / Dijkstra route search',
    status: 'implemented',
    purpose: 'Find a collision-free route to the target.',
    inputs: 'Inflated occupancy grid, start pose, target',
    outputs: 'Waypoints, route length, nodes expanded, planning time',
    implementation:
      '8-connected A* with an octile heuristic, no corner cutting and a soft clearance cost, followed by line-of-sight smoothing. Dijkstra (listed in the deck) is not used separately.',
    modules: ['backend/app/navigation/astar.py', 'backend/app/navigation/grid.py'],
    live: 'plan',
  },
  {
    id: '2.4',
    layer: 'decision',
    title: 'Obstacle avoidance',
    deck: 'Dynamic replanning',
    status: 'implemented',
    purpose: 'Keep the route safe as the world changes.',
    inputs: 'Live grid, current route, environment feedback',
    outputs: 'Replan request, safety stop or Blocked state',
    implementation:
      'Three layers: the next 4 m of route is checked against the grid every tick (a blocked route triggers A* again); measured LiDAR/ultrasonic clearance in the driving corridor slows the robot and stops it below the stop distance; and a ground-truth layer vetoes motion that would close clearance below 5 cm. With no fresh proximity sensor the robot runs at a fail-safe speed.',
    modules: ['backend/app/simulation/engine.py'],
    live: 'replans',
  },
  {
    id: '3.1',
    layer: 'control',
    title: 'Robot controller',
    deck: 'Translate plan into commands',
    status: 'implemented',
    purpose: 'Convert waypoints into speed and turn-rate commands.',
    inputs: 'Waypoints, robot pose, speed limit',
    outputs: 'Linear and angular velocity commands',
    implementation: 'Pure-pursuit controller with speed, turn-rate and acceleration limits and goal slow-down.',
    modules: ['backend/app/control/controller.py'],
    live: 'robot',
  },
  {
    id: '3.2',
    layer: 'control',
    title: 'Robot movement',
    deck: 'Motion and action execution',
    status: 'simulation',
    purpose: 'Execute the commands.',
    inputs: 'Velocity commands',
    outputs: 'New robot pose',
    implementation:
      'Differential-drive kinematics integrated at a fixed 20 Hz timestep. No physical motors are driven.',
    modules: ['backend/app/control/controller.py'],
    live: 'robot',
  },
  {
    id: '3.3',
    layer: 'control',
    title: 'Environment feedback',
    deck: 'Position, obstacles, progress',
    status: 'implemented',
    purpose: 'Close the loop: report the new state to planning and to the dashboard.',
    inputs: 'Pose, obstacle positions, contacts',
    outputs: 'Clearance and contact checks (PyBullet), progress, WebSocket telemetry at 10 Hz',
    implementation:
      'Collision and clearance are verified against PyBullet geometry each tick; telemetry is streamed to the dashboard with sequence numbers.',
    modules: ['backend/app/simulation/physics.py', 'backend/app/api/websocket.py'],
    live: 'safety',
  },
  {
    id: '3.4',
    layer: 'control',
    title: 'Live telemetry',
    deck: 'Added for clarity: WebSocket /ws/telemetry from the deck’s APIs',
    status: 'implemented',
    purpose: 'Stream authoritative state to the dashboard.',
    inputs: 'Engine snapshot (pose, route, events, perception, safety)',
    outputs: 'Versioned JSON messages with strictly increasing sequence numbers',
    implementation:
      'An asyncio task samples the engine at 10 Hz and fans out through per-client queues of size 1, so slow clients receive the newest state instead of a backlog.',
    modules: ['backend/app/api/websocket.py', 'frontend/src/hooks/useTelemetry.js'],
    live: 'telemetry',
  },
];

// Known limitations per stage, shown in the architecture explorer.
export const STAGE_LIMITS = {
  '1.1': 'Simulated sensors only: simple rendered shapes, ideal geometry plus seeded noise; no lens distortion, multipath or real hardware.',
  '1.2': 'No denoising or filtering stage; frames are only encoded and resized.',
  '1.3': 'COCO-trained YOLOv8 rarely recognises rendered primitives; the default detector is ground truth, not a model.',
  '1.4': 'Tracks use a simple nearest-neighbour association; no prediction of where moving obstacles go next.',
  '2.1': 'The operator chooses the target; it is not recognised automatically from vision.',
  '2.2': 'Rule-based state machine; it does not weigh alternative actions or costs beyond the planner.',
  '2.2a': 'Built from simulator geometry; it is not yet built from perception (no SLAM).',
  '2.3': 'Grid-resolution limited (0.2 m); Dijkstra from the deck is not implemented separately.',
  '2.4': 'Moving obstacles are avoided at their current position only; waiting is limited to 8 s before Blocked.',
  '3.1': 'Tuned for this simulated robot; no wheel slip, latency or actuator dynamics.',
  '3.2': 'Kinematic motion in simulation; no physical motors are driven.',
  '3.3': 'Feedback is ground truth from the simulator, not from real sensors.',
  '3.4': 'Single-process server; clients receive the latest snapshot only, not a full history.',
};

// Slide 4: Data flow (text version of the pipeline)
export const DATA_FLOW = [
  'Camera / sensors',
  'Image processing (OpenCV)',
  'Object, obstacle and people detection (YOLO)',
  'Scene understanding',
  'Target identification',
  'Decision engine',
  'Path planning (A*)',
  'Obstacle avoidance',
  'Robot controller',
  'Robot movement',
  'Environment feedback',
];
export const DATA_FLOW_LOOP = 'Feedback loops back to obstacle avoidance and path planning (continuous replanning).';

// Slide 4: APIs and interfaces
export const INTERFACES = [
  {
    name: 'FastAPI REST APIs',
    deck: 'Start/stop navigation, set target, fetch map and status (e.g. POST /navigate, POST /target, GET /map, GET /status).',
    status: 'implemented',
    actual:
      'All listed endpoints plus pause/resume, reset, path, detections, obstacles and perception controls. Interactive documentation at /docs on the backend.',
  },
  {
    name: 'WebSocket /ws/telemetry',
    deck: 'Live robot pose, detections, path and navigation updates to the dashboard.',
    status: 'implemented',
    actual: 'Versioned JSON at 10 Hz with sequence numbers, bounded per-client queues and automatic client reconnect.',
  },
  {
    name: 'YOLO model interface',
    deck: 'In-process PyTorch inference on each processed frame.',
    status: 'fallback',
    actual: 'In-process Ultralytics inference on a worker thread when weights exist; otherwise the labelled simulated detector.',
  },
  {
    name: 'Simulation API',
    deck: 'PyBullet Python API for sensor data, robot state and motor commands.',
    status: 'partial',
    actual:
      'PyBullet provides camera images and collision/contact queries. Robot motion comes from our own kinematic controller rather than PyBullet motor commands, for deterministic, repeatable demos.',
  },
];

// Slide 4: Tech stack (deck) vs what this prototype actually uses
export const TECH_STACK = [
  {
    area: 'Frontend',
    deck: 'React 18, Vite, React Router, Axios, Framer Motion, Lucide React',
    used: 'React 18, Vite, React Router, Axios, Framer Motion (reduced-motion aware), HTML Canvas',
    status: 'implemented',
    note: 'Lucide React was replaced by small inline SVG icons to match the design direction.',
  },
  {
    area: 'Backend',
    deck: 'Python, FastAPI (REST + native WebSocket)',
    used: 'Python 3.10, FastAPI, Pydantic, Uvicorn',
    status: 'implemented',
  },
  {
    area: 'Computer vision',
    deck: 'OpenCV, NumPy',
    used: 'OpenCV (frame encoding), NumPy (grid, ray casting, masks)',
    status: 'implemented',
  },
  {
    area: 'AI / detection',
    deck: 'YOLOv8 (Ultralytics), PyTorch',
    used: 'Ultralytics YOLOv8n on CPU via PyTorch when weights are present',
    status: 'fallback',
    note: 'Without weights, a ground-truth simulated detector is used and labelled.',
  },
  {
    area: 'Navigation',
    deck: 'A* path planning on occupancy grid + waypoint-based navigation',
    used: 'A* on an inflated occupancy grid, path smoothing, pure-pursuit waypoint following',
    status: 'implemented',
  },
  {
    area: 'Real-time communication',
    deck: 'WebSocket (FastAPI)',
    used: 'FastAPI WebSocket /ws/telemetry',
    status: 'implemented',
  },
  {
    area: 'Simulation',
    deck: 'PyBullet',
    used: 'PyBullet (headless DIRECT mode) for collision checks and camera rendering; kinematic robot motion',
    status: 'fallback',
    note: 'If PyBullet is not installed, analytic 2D collision and a ray-cast camera are used and reported in System status.',
  },
];

// Slide 5: Market research / analysis (qualitative, as presented in the deck)
export const MARKET = {
  columns: ['Target users', 'Market size', 'Potential revenue model', 'Expected growth'],
  rows: [
    ['Industrial automation', 'Large and growing', 'Robotics-as-a-Service (RaaS)', 'Rising AI adoption'],
    ['Warehousing and logistics', 'Expanding robotics market', 'Enterprise solutions', 'Autonomous navigation'],
    ['Robotics research', 'Multiple industry applications', 'Custom integration', 'Computer vision growth'],
    ['Emergency response', 'Emerging opportunity', 'Deployment and support', 'Smart robotics adoption'],
  ],
  note: 'Qualitative assessment from the team’s pitch deck. No market figures were sourced or verified for this prototype.',
};

export const LIMITATIONS = [
  'Everything runs in simulation. No physical robot, camera, depth sensor or LiDAR is connected.',
  'Collision avoidance uses ground-truth obstacle geometry from the simulator, not camera detections.',
  'The camera image is a simple synthetic render. YOLOv8 is trained on real photographs and may detect little in it; its results are shown unedited.',
  'Robot motion is kinematic (no wheel slip or dynamics). PyBullet is used for collision and rendering, not for driving the robot.',
  'The target is chosen by the operator; automatic target recognition from vision is not implemented.',
  'Moving obstacles are avoided at their current position; their motion is not predicted.',
  'No accuracy, latency or success-rate benchmarks have been measured, so none are claimed.',
];
