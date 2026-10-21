# VISTARA-X

**Vision-Based Autonomous Navigation System** — *Beyond Seeing. Into Understanding.*

VISTARA-X is a simulation-first autonomous robotics platform. A simulated robot maps its surroundings with LiDAR-based SLAM, understands spoken or typed commands in English and Hindi, plans a collision-free route with A\*, follows it with a pure-pursuit controller, and replans in real time when obstacles block its path. Every step can be operated without audio. A React dashboard visualises the live mission using authoritative telemetry streamed from a FastAPI backend.

> **Mission:** Understand the environment, understand the user's intention, and navigate safely toward the requested destination.

---

## Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Mapping and localisation](#mapping-and-localisation)
- [Voice and text commands](#voice-and-text-commands)
- [Accessibility](#accessibility)
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
| Mapping and localisation | Log-odds occupancy mapping from the simulated LiDAR; wheel-odometry prediction corrected by correlative scan matching (2D SLAM); autonomous frontier exploration; planning on the live SLAM map or an imported map | Implemented (simulated sensors); ROS 2 live SLAM not set up |
| Map files | Save, load, export and import maps in ROS map_server format (PGM + YAML) | Implemented |
| Voice and text commands | English, Hindi and Hinglish; local Whisper speech recognition; deterministic intent parser; named destinations; validation and confirmation before moving; spoken and written responses | Implemented |
| Accessibility | Text-first operation, persistent transcripts, visual alert centre, accessible display mode (large text, high contrast, persistent alerts), keyboard operation | Implemented |
| Trap-the-robot challenge | Interactive game: the viewer places up to 5 barriers while the robot drives; the robot either replans through every gap or reports *Blocked*, with the collision count shown live | Implemented |

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
│  ├─ SLAM: scan matching + map    Request threads          │
│  ├─ frontier exploration         ├─ command parser        │
│  └─ PyBullet collision checks    └─ Whisper speech-to-text│
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
pip install -r requirements-optional.txt   # optional: PyBullet, YOLOv8, Whisper
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
| `POST /navigation/estop` | Emergency stop: always succeeds, with or without a mission |
| `GET /mapping?which=slam\|imported` | Map cells, resolution, origin, pose estimate, trajectory, last scan, localisation status |
| `POST /mapping/explore` · `/mapping/control` · `/mapping/planner` | Start exploration; pause/resume/clear mapping; choose the planner map (`simulator`, `slam`, `imported`) |
| `GET /mapping/export?file=pgm\|yaml`, `POST /mapping/save` · `/load` · `/import` | ROS map_server files: download, save, load, import (`{name, yaml, pgm_base64}`) |
| `GET /places` | Named destinations of the current scenario with Hindi names and aliases |
| `POST /commands/interpret` · `/commands/{id}/confirm` · `/cancel`, `GET /commands` | Command pipeline and transcript history |
| `GET /speech/status`, `POST /speech/load`, `POST /speech/transcribe?language=en\|hi` | Whisper status, model warm-up, transcription of a raw audio body |
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
| `VISTARA_MAPS_DIR` | `backend/maps` | Where saved maps (PGM + YAML) are stored |
| `VISTARA_WHISPER_MODEL` | `base` | Whisper size: `tiny`, `base`, `small`, `medium` |

## Mapping and localisation

All mapping in this prototype is **simulation-generated**: the inputs are the simulated LiDAR and wheel odometry, and the result is labelled as such in the dashboard and API.

### How the map is built

1. **Prediction.** Every tick the pose estimate moves by the wheel-odometry increment (odometry has slip noise, so on its own it drifts).
2. **Correction.** For every LiDAR scan (10 Hz) a correlative scan matcher searches ±16 cm and ±4° around the prediction, coarse then fine, for the pose whose scan end points best fit the obstacles already mapped (a likelihood field with bilinear interpolation).
3. **Mapping.** The scan is fused into a 0.1 m log-odds occupancy grid at the corrected pose: cells along each ray become more likely free, the cell at the end of a ray more likely occupied, and untouched cells stay unknown.
4. **Status.** Localisation quality comes from the match score (no ground truth involved). Because this is a simulation, the pose error against the true pose is also shown, for evaluation only.

There is no loop closure, so error can still grow on very long runs. Measured on a 14-goal loop in the warehouse (2,212 scans): the SLAM pose error stayed between 8 and 10 cm (maximum 19 cm), while odometry alone drifted to 140 cm.

**Exploration.** *Explore and map automatically* drives the robot to frontiers (free cells next to unknown cells) on the SLAM map until none are reachable. In the warehouse it maps about 83–90% of the area in about 30 s of simulated time with no collisions.

### Mapping modes

| Mode | Status | How |
|---|---|---|
| **A: Live SLAM on real sensors (ROS 2)** | Not available in this environment | Needs ROS 2, SLAM Toolbox, Nav2 and a robot or a recorded bag; see below |
| **B: Simulated mapping** | Implemented | Default: the live SLAM map above, from simulated sensors |
| **C: Existing map import** | Implemented | ROS map_server PGM + YAML: dashboard *Import map*, or `POST /mapping/import` |

### Planning on a map

The planner can use *simulator geometry* (default), the *live SLAM map*, or an *imported map* (Mapping panel > *Planner uses*, or `POST /mapping/planner`).

- **Live SLAM map:** unknown space is traversable, and obstacles appear as the LiDAR maps them. The route is re-checked every tick, so newly mapped obstacles cause a stop and a replan.
- **Imported map:** unknown space is treated as an obstacle. Obstacles that are not in the map (people, added objects) come from live LiDAR returns.
- In every mode the final safety veto still uses simulator geometry.

### Map files

- Saved maps use the ROS map_server format: PGM (occupied 0, free 254, unknown 205; first row = top of the map) and YAML (`resolution`, `origin`, `negate`, `occupied_thresh`, `free_thresh`).
- The map frame is the simulator's world frame in metres, with origin (0, 0) at the bottom-left corner.
- An imported map is interpreted with its own resolution, origin and thresholds.
- A floor-plan picture is **not** a metric map until it has been converted to an occupancy grid at a known scale. Nothing here does that automatically.
- `backend/maps/warehouse_demo` is a documented demo map made by exploration (see [backend/maps/README.md](backend/maps/README.md)).

### Mode A: live SLAM with ROS 2 (setup guide, not part of this prototype)

ROS 2 is not installed on the development machine, so no live SLAM on real sensors has been run or validated. To add it:

1. Install ROS 2 Humble or Jazzy on Ubuntu 22.04/24.04 (Windows support is limited). Then run `sudo apt install ros-<distro>-slam-toolbox ros-<distro>-navigation2 ros-<distro>-nav2-bringup`.
2. Publish `/scan` (`sensor_msgs/LaserScan`), `/odom` and the `odom → base_link → laser` transforms from the robot or a recorded bag.
3. Run `ros2 launch slam_toolbox online_async_launch.py`, then save with `ros2 run nav2_map_server map_saver_cli -f mymap`.
4. Import `mymap.pgm` and `mymap.yaml` into VISTARA-X (Mode C). A ROS 2 bridge that streams `/map` and the robot pose into this backend live is future work.

## Voice and text commands

The command workflow:

**microphone or keyboard → speech recognition → language → transcript → intent → destination → validation → confirmation → navigation → response**

- **Speech recognition:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) runs Whisper locally on the backend, so audio is not sent to a cloud service.
  - The browser records a clip of up to 8 s; PyAV decodes it, so ffmpeg is not required.
  - The `base` model (default) takes about 3 s per command with a language hint and about 6 s with automatic detection on a 4-core laptop CPU. `small` is more accurate, especially for Hindi, but about 4× slower.
  - Whisper often labels spoken Hindi as Urdu; such clips are re-transcribed as Hindi so the text comes out in Devanagari.
  - Empty or silent clips and unsupported languages are reported, never guessed.
  - *Browser speech recognition* is offered as an alternative where the browser supports it. It is labelled as online, because Chrome sends the audio to Google.
- **Intent parsing is deterministic.** Keyword rules cover English, Hindi (Devanagari) and Hinglish; no language model is involved.
  - Intents: go to a place, return to the start, stop, pause, resume. Constraints: *safe/carefully/सुरक्षित* (0.30 m margin, max 0.6 m/s) and *slowly/धीरे* (max 0.5 m/s).
  - A stop word anywhere in the text wins.
- **Destinations** come only from the scenario's named places (`GET /places`, e.g. Reception / रिसेप्शन, Storage room / स्टोर रूम, Charging dock, Loading bay, Exit, Starting point) or from explicit coordinates. Unknown or ambiguous places get a clarification question listing the known places.
- **Validation:** the target must be valid on the current planner map, and A\* checks whether a route exists. A new destination waits for **Confirm** unless *Trusted mode* is on. A known place with no route is never started automatically; if confirmed, the robot reports *Blocked* without moving.
- **Stop, pause and resume** run immediately. **Emergency stop** (`POST /navigation/estop`) is a separate button that does not depend on speech, language or parsing, and always succeeds.
- **Responses** are written in the language of the command (English, Hindi or Hinglish) and can optionally be spoken with the browser's text-to-speech. The text is always on screen, and the transcript history is kept for the session.

Examples: *Robot ko reception tak le jao* · *Take the robot to the storage room* · *Find a safe route to the exit* · *रुको* · *थोड़ा रुको* · *फिर से चलो* · *वापस जाओ*.

**Model setup:** `pip install faster-whisper` is in `requirements-optional.txt`. The model downloads once on first use (base ~145 MB, small ~480 MB) into the Hugging Face cache. Choose the size with `VISTARA_WHISPER_MODEL`, and click *Speak a command* once before the demo, or call `POST /speech/load`, so that model loading does not delay the first command.

## Accessibility

A deaf or hard-of-hearing user can run every step without audio:

- **Commands without speech:**
  - Typed commands, example chips and a destination selector.
  - A recording level meter, so the microphone state is visible without sound.
  - A persistent transcript history; spoken responses are optional and always captioned.
- **Visual alerts:** the alert centre shows obstruction, replanning, *Blocked*, collision, error and goal-reached alerts as text with an icon, never by colour or sound alone. *Blocked* and *Error* stay visible for as long as the state lasts.
- **Accessible mode** (Display and alert settings) combines larger text (all sizes scale), high contrast with a strong focus ring, and alerts that stay until dismissed. Each setting can also be changed on its own, including how long alerts stay (5, 10 or 30 s, or until dismissed).
- **Keyboard and screen readers:** every control is keyboard-operable with a visible focus. Live regions announce command results and alerts, and Hindi text is marked with `lang="hi"`.
- **Sign language:** recognition is **not** implemented. It would need a validated sign-language model and is listed as future work.

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

Weights added to `backend/models/` while the backend is running are picked up the next time `GET /models` is called; no restart is needed. With `yolov8n.pt` and `yolov8s.pt` both present, `test_two_real_models_run_in_multi_mode` runs both real models on a rendered simulator frame (it is skipped when either file or `ultralytics` is missing). Policy logic such as cascade triggers, failures and latency adaptation is also covered with test doubles.

## Perception and model weights

Model weights are not downloaded automatically and are excluded from version control. To enable YOLOv8 inference, place `yolov8n.pt` (and optionally `yolov8s.pt` as a secondary model) in `backend/models/` (see [backend/models/README.md](backend/models/README.md)) and select **YOLOv8 inference** in the dashboard's Perception panel.

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
| *Speak a command* is disabled or says Whisper unavailable | `pip install faster-whisper`; the first use downloads the model (internet needed once). Typed commands always work. |
| Microphone permission denied | Allow the microphone for the site in the browser, or type the command. |
| Voice commands are slow | Whisper runs on the CPU: pick the spoken language (skips detection) or use `VISTARA_WHISPER_MODEL=tiny`. |
| Robot moves slowly or telemetry shows *Delayed* on a low-power laptop | The browser is competing with the simulation for CPU. Tick **Demo mode** in the mission overview (20 fps 3D without shadows, robot speed 0.6 m/s; unticking restores the previous speed), untick **Motion effects** or use the **Plan** view; close other heavy tabs. The backend raises itself to above-normal priority on Windows (`VISTARA_HIGH_PRIORITY`). |

## Judge demonstration guide

No code edits are needed. Start both applications (see *Getting started*) and open `http://localhost:5173/mission`. On a slower laptop, tick **Demo mode** in the mission overview. Before the demo, click **Speak a command** once so the Whisper model is loaded.

| # | Action | What to verify | Uses |
|---|---|---|---|
| 1 | Open the console; the warehouse 3D environment loads. | Racking, pallets, a patrolling person, the robot at (1.5, 6.0); the HUD shows map %, SLAM quality and pose error. | Simulation |
| 2 | Mapping panel: click **Explore and map automatically** (or load the documented map: *Save, load…* > `warehouse_demo` > **Load**). | The robot drives to frontiers; the map fills in (free, occupied, unknown); the estimated trajectory follows the true one; *Exploration finished* at about 83–90%. | Simulated LiDAR and odometry, SLAM; or imported map |
| 3 | Inspect the map. | Occupancy grid, robot pose and heading, trajectory, latest scan (orange), localisation *Good*, pose error in cm, resolution 0.1 m, origin (0, 0). | Simulation |
| 4 | Commands panel: type **Robot ko reception tak le jao** (or press **Speak a command** and say it, or say *Take the robot to the storage room*). | — | Text, or local Whisper |
| 5 | Read the command card. | Transcript, language (*Hinglish* / *Hindi* / *English*), intent, resolved destination with coordinates, *Route found, N m*, robot response in the same language. Nothing moves yet. | Deterministic parser |
| 6 | Click **Confirm and go**. | Status *Planning* → *Navigating*; the A\* route appears in 3D and on the map. | Simulation |
| 7 | Click **Drop obstacle on route** (Mission controls). | The robot stops; status *Replanning*; a visual alert *Route blocked: robot stopped and replanning*; the event log names the obstacle. | Simulation, safety layers |
| 8 | Alternative route. | A new validated route; Navigation lists the replan. | Simulation |
| 9 | Completion. | *Destination reached* alert; status *Goal reached* within 0.2 m; collisions 0. | Simulation |
| 10 | Accessible text-first run: open *Display and alert settings*, tick **Accessible mode**, then repeat 4–9 using only the keyboard (Tab to *Type a command*, type **Take the robot to the exit**, Enter, Tab to *Confirm and go*, Enter). | Large text, high contrast, alerts stay until dismissed; no step needs audio. | Text only |
| 11 | Invalid and blocked destinations: type **Take the robot to the cafeteria**; then click **Run blocked-route demo**. | First: *I don't know that place. Known places: …* (no guessed location). Second: status *Blocked*, a red *No safe route* banner, 0.00 m travelled. | Parser; simulation |

At any time **Emergency stop** (Commands panel) halts the robot directly. Interactive extra: click **Start challenge** in *Trap the robot* and hand the judge the mouse; three barriers across the gap at x = 15 seal the robot in (it reports *Blocked*), and fewer leave a gap it finds.

Optional: add a *Person (walking)* across the route, switch the LiDAR off to see the fail-safe speed and *No LiDAR input* in the Mapping panel, or select *YOLOv8* in Detection models to run real inference on the camera frame. **Run guided demo** automates the obstacle-and-replan part.

### Mission states

`idle` → `planning` → `navigating` ⇄ `replanning` → `goal_reached`, with `paused`, `stopped` (operator), `blocked` (no valid route; with moving obstacles the robot first waits up to 8 s) and `error` (internal fault, robot halted). Every new route is re-validated cell by cell against the occupancy grid before the robot moves.

## Capability status

| Status | Capabilities |
|---|---|
| **Implemented** | A\* planning on an inflated occupancy grid, route validation, replanning state machine, pure-pursuit control, three-layer safety (grid route check, measured proximity, ground-truth veto), 2D SLAM (odometry + scan matching + log-odds map) and frontier exploration, planning on SLAM or imported maps, ROS map_server import/export, deterministic English/Hindi/Hinglish command parser with validation and confirmation, local Whisper speech recognition, emergency stop, visual alert centre and accessible mode, mission states, REST + WebSocket API, 3D/2D visualisation, model registry and fusion, guided and blocked demos, trap-the-robot challenge, automated tests |
| **Simulated** | All sensors (camera, depth, LiDAR, ultrasonic, IMU, odometry), and therefore every SLAM map built here; robot motion (kinematic), people and obstacles, PyBullet collision checks and rendering |
| **Unavailable here** | Real hardware; ROS 2 live SLAM (not installed); GPU inference; a Hindi text-to-speech voice on the development machine |
| **Future** | ROS 2 bridge (SLAM Toolbox + Nav2) and real sensors, loop closure, real RGB-D camera and motor-controller integration, sign-language recognition, vision-language objectives, multi-robot coordination |

## Limitations and roadmap

**Current limitations**

- All operation is simulated; no physical robot or sensors are connected.
- The planner uses simulator geometry by default and can plan on the SLAM or an imported map; the final safety veto always uses simulator geometry. Camera detections are used for visualisation and the person-proximity speed limit only.
- SLAM has no loop closure; its error is measured only in simulation (against ground truth). It has never run on real sensor data.
- Speech recognition runs on the CPU (about 3–6 s per command with `base`). English speech was tested with synthetic (TTS) audio; Hindi speech recognition has not been tested with recorded Hindi speech because no Hindi voice or recording was available. Hindi text commands are tested.
- The command parser understands the listed phrasings and place names, not arbitrary language; anything else is answered with a clarification request.
- Sign-language recognition is not implemented.
- Robot motion is kinematic. PyBullet is used for collision checks and rendering, not for actuation.
- Targets are selected by the operator; automatic target recognition is not implemented.
- Moving obstacles are avoided at their current position; their motion is not predicted.
- Apart from the SLAM pose error and Whisper processing times reported here, no accuracy, latency or success-rate benchmarks have been measured over many runs.
- All sensors are simulated against the simulator's geometry; no physical sensor is connected.
- The YOLO weights (`yolov8n.pt`, `yolov8s.pt`) are COCO-trained; COCO classes rarely appear in the rendered scene, so real models often report few or no detections. Inference runs on the CPU only.
- Automated browser tests run headless with software WebGL and reduced motion; full-motion 3D was checked visually in screenshots.

**Roadmap**

1. **Intelligent simulation** — current prototype.
2. **Real-world prototype** — RGB/depth cameras, motor-controller integration, sim-to-real validation.
3. **Advanced perception** — ROS 2 SLAM on real LiDAR, loop closure, multi-sensor fusion, vision-language models.
4. **Scalable autonomy** — natural-language objectives, multi-robot coordination, real-world deployment.

---

Developed by Team Hack01 for Hack in Hills ’26.
