# VISTARA-X

**Vision-Based Autonomous Navigation System** — *Beyond Seeing. Into Understanding.*

VISTARA-X is a simulation-first autonomous robotics platform. A simulated robot perceives its environment through a rendered camera, builds an occupancy grid, plans a collision-free route with A\*, follows it with a pure-pursuit controller, and replans in real time when obstacles block its path. A React dashboard visualises the live mission using authoritative telemetry streamed from a FastAPI backend.

> **Mission:** Navigate to the target while avoiding obstacles.

---

## Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Perception and model weights](#perception-and-model-weights)
- [Testing](#testing)
- [Deployment and security](#deployment-and-security)
- [Troubleshooting](#troubleshooting)
- [Judge demonstration guide](#judge-demonstration-guide)
- [Capability status](#capability-status)
- [Limitations and roadmap](#limitations-and-roadmap)

---

## Overview

Autonomous robots must understand their surroundings, identify relevant objects and people, navigate toward an objective, and avoid obstacles in real time. VISTARA-X implements this as one continuous loop:

**Observe → Detect → Understand → Decide → Plan → Move → Monitor → Replan**

The system runs entirely in simulation, with module boundaries designed for later integration of real cameras, depth sensors, LiDAR and motor controllers.

## Features

| Capability | Implementation | Status |
|---|---|---|
| Simulation | Deterministic scenarios with static, inserted and moving obstacles; fixed 20 Hz timestep | Implemented |
| Physics and collision | PyBullet (headless) clearance and contact verification | Implemented; analytic 2D fallback |
| Camera | PyBullet-rendered RGB, depth and segmentation | Implemented; ray-cast fallback |
| Simulated sensors | 2D LiDAR, six-channel ultrasonic ring, IMU with gyro bias, wheel odometry with slip, RGB/depth camera; health, rate and data age per sensor | Implemented (all simulated, labelled) |
| Object detection | Model registry for YOLO weights: primary/secondary models, single/cascade/multi policy, class-aware NMS fusion, latency budget with adaptive frame stride | Implemented when weights are present; labelled ground-truth fallback |
| Scene understanding | Class-to-obstacle policy, obstacle tracking, explored/unknown map | Implemented |
| Path planning | 8-connected A\* on an inflated occupancy grid, line-of-sight smoothing | Implemented |
| Control | Pure-pursuit waypoint following with speed, turn-rate and acceleration limits | Implemented |
| Obstacle avoidance | Route-obstruction checks every tick; measured LiDAR/ultrasonic slow-down and stop in the driving corridor; ground-truth safety veto; fail-safe speed when proximity sensors are unavailable; validated replanning | Implemented |
| Failure handling | Honest *Blocked* state when no safe route exists | Implemented |
| Telemetry | Versioned WebSocket stream with sequence numbers and bounded queues | Implemented |
| 3D digital twin | Three.js warehouse (racking, pallets, crates, barriers, person), differential-drive robot with wheels, casters and camera mast, LiDAR points, route ribbons, orbit/top/follow cameras; 2D plan view and automatic fallback | Implemented |
| Dashboard | Mission overview with quick controls and health, simulator, controls, perception, sensors, navigation (occupancy grid, route validity, replanning history), telemetry, event log, system health, guided and blocked-route demos | Implemented |

## Architecture

```text
┌──────────────── frontend/ (React + Vite) ────────────────┐
│  Overview · Architecture explorer · Live mission console │
└──────────────┬───────────────────────────▲───────────────┘
               │ REST (commands)           │ WebSocket /ws/telemetry (10 Hz)
┌──────────────▼───────────────────────────┴───────────────┐
│                  backend/ (FastAPI)                       │
│                                                           │
│  Simulation thread (20 Hz)       Perception thread        │
│  ├─ mission state machine        ├─ camera render         │
│  ├─ occupancy grid + A*          ├─ YOLOv8 / fallback     │
│  ├─ pure-pursuit controller      ├─ model registry + NMS  │
│  ├─ simulated sensor suite       └─ scene understanding   │
│  └─ PyBullet collision checks                             │
└───────────────────────────────────────────────────────────┘
```

A single simulation thread owns the robot, so concurrent controllers cannot conflict. Perception runs on a separate worker thread so that model inference never delays control or API responses.

### Repository layout

```text
VISTARA-X/
├── backend/            FastAPI service, simulation, perception, navigation, control, tests
├── frontend/           React application, dashboard, content pages, E2E tests
└── README.md
```

## Getting started

### Prerequisites

- Python 3.10 or later
- Node.js 20 or later
- Optional: Microsoft C++ Build Tools (Windows only, required to compile PyBullet)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: PyBullet and YOLOv8
python -m uvicorn app.main:app --reload --port 8000
```

The API is served at `http://localhost:8000`, with interactive documentation at `/docs` in development.

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and select **Live mission**. See the [judge demonstration guide](#judge-demonstration-guide).

## API

Interactive reference at `http://localhost:8000/docs` (development). All responses use JSON; errors are `{"error": {"code", "message", "details"?}}`.

| Endpoint | Purpose |
|---|---|
| `GET /health`, `GET /status` | Service, simulation, planner, controller, perception and telemetry status |
| `GET /map`, `GET /path` | Occupancy grid (occupied, inflated, observed, unknown, LiDAR-observed cells) and current route |
| `GET /detections`, `GET /models`, `GET /sensors` | Perception output, model registry, sensor health and readings |
| `POST /target`, `POST /navigate` | Set the target; start a mission |
| `POST /navigation/pause` · `/resume` · `/stop` | Mission lifecycle |
| `POST /simulation/reset` | Load a scenario: `warehouse`, `slalom`, `enclosed` |
| `POST /simulation/obstacles`, `DELETE /simulation/obstacles/{id}` | Add or remove an obstacle; `{"label":"person","patrol_to":{"x","y"}}` adds a walking person (`POST /obstacles/{id}/move` moves one) |
| `POST /obstacles/inject` | Drop a barrier across the active route (demo) |
| `POST /models/select`, `POST /sensors/configure`, `POST /perception/config` | Model policy, sensor settings, frame processing |
| `WS /ws/telemetry` | Versioned state stream at 10 Hz with sequence numbers |

## Configuration

Copy the example files and adjust as needed. Neither application requires secrets.

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

**Frontend** — all `VITE_*` values are bundled into browser code and must be public.

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend URL. The WebSocket URL is derived from it (`https` → `wss`). |
| `VITE_SITE_URL` | *(empty)* | Public origin. When set, the build emits `sitemap.xml` and a canonical link. |

**Backend**

| Variable | Default | Description |
|---|---|---|
| `VISTARA_ENV` | `development` | `production` disables `/docs` and enables HSTS |
| `VISTARA_CORS_ORIGINS` | `http://localhost:5173,…` | Allowed browser origins (REST and WebSocket) |
| `VISTARA_SIM_HZ` | `20` | Simulation rate (timestep = 1 / rate) |
| `VISTARA_TELEMETRY_HZ` | `10` | WebSocket broadcast rate |
| `VISTARA_PERCEPTION_HZ` | `4` | Camera processing rate |
| `VISTARA_GRID_RESOLUTION` | `0.2` | Occupancy-grid cell size (m) |
| `VISTARA_MAX_SPEED` | `0.9` | Default speed limit (m/s) |
| `VISTARA_SAFETY_MARGIN` | `0.15` | Clearance added to the robot radius (m) |
| `VISTARA_PHYSICS` | `auto` | `auto`, `pybullet` or `analytic` |
| `VISTARA_PYBULLET_GUI` | `0` | `1` opens the PyBullet GUI (requires a display) |
| `VISTARA_DETECTOR` | `simulated` | Startup detector: `simulated`, `yolov8` or `auto` |
| `VISTARA_YOLO_WEIGHTS` | `models/yolov8n.pt` | Path to YOLOv8 weights |
| `VISTARA_YOLO_CONFIDENCE` | `0.25` | Detection confidence threshold |
| `VISTARA_LOG_LEVEL` | `INFO` | Logging verbosity |

## Sensors

All sensors are **simulated**: they measure the simulator's geometry with seeded noise and are labelled as simulated everywhere. No hardware is connected.

| Sensor | Default rate | Measures | Used for |
|---|---|---|---|
| RGB camera | 4 Hz | Rendered frame (PyBullet TinyRenderer) | Object detection |
| Depth | 4 Hz | Depth buffer of the same render | Range of detections |
| 2D LiDAR | 10 Hz | 360°, 2° resolution, 8 m range, σ = 1 cm | Corridor clearance (slow/stop), LiDAR-observed cells in `GET /map` |
| Ultrasonic ring | 10 Hz | 6 cones (0°, ±40°, ±90°, 180°), 2 m range | Close-range stop on the forward channel |
| IMU | 20 Hz | Yaw (integrated, with gyro bias), yaw rate, acceleration | Reported; drift shown against ground truth |
| Wheel odometry | 20 Hz | Encoder ticks, wheel speeds, dead-reckoned pose with slip | Reported; drift shown against ground truth |

Configure with `POST /sensors/configure` (e.g. `{"sensor":"lidar","rate_hz":5,"params":{"fov_deg":180}}`) or from the Sensors panel. Safety thresholds: `{"sensor":"safety","params":{"slow_distance":0.9,"stop_distance":0.3}}`. If both LiDAR and ultrasonic are disabled or stale, the robot drives at a fail-safe 30 % speed and the ground-truth collision layer remains active.

## Detection models

The registry discovers every `*.pt` file in `backend/models/` (plus `VISTARA_YOLO_WEIGHTS`) and lists it in `GET /models` with load status, task, device and measured latency. Choose models and policy in the dashboard or with `POST /models/select`:

```json
{"primary": "yolov8n", "secondary": "yolov8s", "mode": "cascade", "confidence": 0.3, "iou": 0.5, "latency_budget_ms": 250}
```

- **single**: primary only (use on low-power machines).
- **cascade**: the secondary model runs only when the primary reports a trigger class (default `person`) or a detection with confidence between 0.25 and 0.5.
- **multi**: the secondary also runs on every Nth frame.

Results are merged with class-aware NMS; when two models agree the result lists both, but confidence is not increased. If the average frame time exceeds the budget, the secondary model is suspended first, then frames are skipped (stride up to 4). A model that fails to load or infer is marked unavailable and perception falls back to the labelled simulated detector; navigation safety never depends on the detector.

Only `yolov8n.pt` (COCO) was available while building this prototype, so cascade and multi modes were verified with test doubles, not with two real models.

## Perception and model weights

Model weights are not downloaded automatically and are excluded from version control. To enable YOLOv8 inference, place `yolov8n.pt` in `backend/models/` (see [backend/models/README.md](backend/models/README.md)) and select **YOLOv8 inference** in the dashboard's Perception panel.

Without weights, the system uses a simulated detector that projects ground-truth geometry into the camera. It is clearly labelled in the interface and reports no confidence scores. The camera image is a synthetic render, so a COCO-trained YOLOv8 model may detect few or no objects; its output is displayed unmodified.

## Testing

```bash
# Backend: unit, API, WebSocket and mission integration tests
cd backend
python -m pytest

# Frontend: production build
cd frontend
npm run build

# End-to-end browser tests (both applications must be running)
pip install playwright
python -m playwright install chromium
python -m pytest frontend/e2e
```

The end-to-end suite accepts `E2E_BACKEND_URL` and `E2E_FRONTEND_URL` to target other ports.

## Deployment and security

- **CORS:** set `VISTARA_CORS_ORIGINS` to the exact production frontend origin. WebSocket connections from other origins are rejected.
- **Transport:** serve the frontend over HTTPS and point `VITE_API_BASE_URL` at an HTTPS backend so telemetry uses `wss://`. HTTPS has not yet been deployed or verified.
- **Input handling:** all requests are validated server-side; errors return structured JSON without internal details. Mutating endpoints are rate-limited per client.
- **Privacy:** the application sets no cookies and loads no analytics or third-party scripts.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `WinError 10013` or "port already in use" | Another process holds the port. Stop it, or run on another port and update `VITE_API_BASE_URL` and `VISTARA_CORS_ORIGINS`. |
| Dashboard shows *Backend unreachable* | Start the backend; the dashboard reconnects automatically. |
| WebSocket closes immediately | The frontend origin is missing from `VISTARA_CORS_ORIGINS`. |
| PyBullet fails to install on Windows | Install the *Desktop development with C++* build tools, or continue without it; the analytic fallback is used and reported. |
| YOLOv8 option is disabled | Weights are missing or `ultralytics` is not installed. |
| Robot moves slowly or telemetry shows *Delayed* on a low-power laptop | The browser is competing with the simulation for CPU. Untick **Motion effects** or use the **Plan** view; close other heavy tabs. The backend raises itself to above-normal priority on Windows (`VISTARA_HIGH_PRIORITY`). |

## Judge demonstration guide

No code edits are needed. Start both applications (see *Getting started*) and open `http://localhost:5173/mission`.

| # | Action | What to verify |
|---|---|---|
| 1 | The warehouse loads (or click **Reset** / **Load** with *Warehouse aisle*). | 3D racking, pallets, a patrolling person and the robot at its start pose (1.5, 6.0). |
| 2 | Inspect the robot: **Follow robot** camera, toggle **LiDAR scan** and **Camera overlay**. | Wheels, casters and camera mast; LiDAR returns on surfaces facing the robot; the Sensors panel shows every sensor *Live (simulated)*. |
| 3 | **Select destination** and click the far end of the aisle (or enter `18.5`, `6`), then **Start mission**. | Status *Planning* then *Navigating*; the A\* route draws on the floor; Navigation shows *Route validity: Valid*. |
| 4 | Watch the robot. | Pose, heading, speed and remaining distance update in Telemetry; wheels turn. |
| 5 | Click **Drop obstacle on route** (or use *Add obstacle* and click on the route). | A barrier appears across the route. |
| 6 | Safety response. | Status *Replanning*; the robot stops; the event log says *Route obstructed by user-N; robot stopped, replanning*; the blocking obstacle is outlined. |
| 7 | Alternative route. | A new route is drawn (the old one fades as a dashed line); the event says *route validated (N samples clear)*; Navigation lists the replan. |
| 8 | Completion. | *Goal reached* only when the robot is within 0.2 m of the target; collisions stay 0. |
| 9 | Blocked scenario: click **Run blocked-route demo** in the Guided demo card (or load *Enclosed bay*, set target `16, 6`, Start). | — |
| 10 | Verify the honest failure. | Status *Blocked* with *No collision-free route to the target exists*; the robot does not move (distance travelled 0.00 m). |
| 11 | Click **Reset** and repeat. | Same start pose and deterministic scenario every time. |

Optional: add a *Person (walking)* across the route, switch the LiDAR off to see the fail-safe speed, or select *YOLOv8* in Detection models to run real inference on the camera frame. **Run guided demo** automates steps 1–8.

### Mission states

`idle` → `planning` → `navigating` ⇄ `replanning` → `goal_reached`, with `paused`, `stopped` (operator), `blocked` (no valid route; with moving obstacles the robot first waits up to 8 s) and `error` (internal fault, robot halted). Every new route is re-validated cell by cell against the occupancy grid before the robot moves.

## Capability status

| Status | Capabilities |
|---|---|
| **Implemented** | A\* planning on an inflated occupancy grid, route validation, replanning state machine, pure-pursuit control, three-layer safety (grid route check, measured proximity, ground-truth veto), mission states, REST + WebSocket API, 3D/2D visualisation, model registry and fusion, guided and blocked demos, automated tests |
| **Simulated** | All sensors (camera, depth, LiDAR, ultrasonic, IMU, odometry), robot motion (kinematic), people and obstacles, PyBullet collision checks and rendering |
| **Unavailable here** | A second set of YOLO weights (cascade/multi policies tested with doubles); real hardware; GPU inference |
| **Future** | Real RGB-D camera and motor-controller integration, LiDAR hardware and sensor fusion, perception-built maps (SLAM), vision-language objectives, multi-robot coordination |

## Limitations and roadmap

**Current limitations**

- All operation is simulated; no physical robot or sensors are connected.
- Collision avoidance uses ground-truth geometry; camera detections are used for visualisation and the person-proximity speed limit only.
- Robot motion is kinematic. PyBullet is used for collision checks and rendering, not for actuation.
- Targets are selected by the operator; automatic target recognition is not implemented.
- Moving obstacles are avoided at their current position; their motion is not predicted.
- No accuracy, latency or success-rate benchmarks have been measured.
- All sensors are simulated against the simulator's geometry; no physical sensor is connected.
- Only one set of YOLO weights (`yolov8n.pt`, COCO) was available, so cascade and multi-model policies are verified with test doubles; COCO classes rarely appear in the rendered scene.
- Automated browser tests run headless with software WebGL and reduced motion; full-motion 3D was checked visually in screenshots.

**Roadmap**

1. **Intelligent simulation** — current prototype.
2. **Real-world prototype** — RGB/depth cameras, motor-controller integration, sim-to-real validation.
3. **Advanced perception** — LiDAR, multi-sensor fusion, vision-language models.
4. **Scalable autonomy** — natural-language objectives, multi-robot coordination, real-world deployment.

---

Developed by Team Hack01 for Hack in Hills ’26.
