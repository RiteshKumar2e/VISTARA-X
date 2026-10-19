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
- [Limitations and roadmap](#limitations-and-roadmap)
- [Documentation](#documentation)

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
| Object detection | Ultralytics YOLOv8 on the camera frame | Implemented when weights are present; labelled ground-truth fallback |
| Scene understanding | Class-to-obstacle policy, obstacle tracking, explored/unknown map | Implemented |
| Path planning | 8-connected A\* on an inflated occupancy grid, line-of-sight smoothing | Implemented |
| Control | Pure-pursuit waypoint following with speed, turn-rate and acceleration limits | Implemented |
| Obstacle avoidance | Route-obstruction checks every tick, safety-stop layer, dynamic replanning | Implemented |
| Failure handling | Honest *Blocked* state when no safe route exists | Implemented |
| Telemetry | Versioned WebSocket stream with sequence numbers and bounded queues | Implemented |
| Dashboard | Interactive map, mission controls, telemetry, perception, event log, guided demo | Implemented |

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
│  ├─ pure-pursuit controller      └─ scene understanding   │
│  └─ PyBullet collision checks                             │
└───────────────────────────────────────────────────────────┘
```

A single simulation thread owns the robot, so concurrent controllers cannot conflict. Perception runs on a separate worker thread so that model inference never delays control or API responses. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

### Repository layout

```text
VISTARA-X/
├── backend/            FastAPI service, simulation, perception, navigation, control, tests
├── frontend/           React application, dashboard, content pages, E2E tests
├── docs/               Architecture, API reference, demo script, content inventory
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

Open `http://localhost:5173` and select **Live mission**. A step-by-step demonstration is available in [docs/DEMO.md](docs/DEMO.md).

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

## Limitations and roadmap

**Current limitations**

- All operation is simulated; no physical robot or sensors are connected.
- Collision avoidance uses ground-truth geometry; camera detections are used for visualisation and the person-proximity speed limit only.
- Robot motion is kinematic. PyBullet is used for collision checks and rendering, not for actuation.
- Targets are selected by the operator; automatic target recognition is not implemented.
- Moving obstacles are avoided at their current position; their motion is not predicted.
- No accuracy, latency or success-rate benchmarks have been measured.

**Roadmap**

1. **Intelligent simulation** — current prototype.
2. **Real-world prototype** — RGB/depth cameras, motor-controller integration, sim-to-real validation.
3. **Advanced perception** — LiDAR, multi-sensor fusion, vision-language models.
4. **Scalable autonomy** — natural-language objectives, multi-robot coordination, real-world deployment.

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Threads, control loop, module responsibilities |
| [docs/API.md](docs/API.md) | REST endpoints, error codes, telemetry schema |
| [docs/DEMO.md](docs/DEMO.md) | Repeatable demonstration script |
| [docs/CONTENT_INVENTORY.md](docs/CONTENT_INVENTORY.md) | Mapping of pitch-deck content to the application |

---

Developed by Team Hack01 for Hack in Hills ’26.
