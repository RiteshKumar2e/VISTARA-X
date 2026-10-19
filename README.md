# VISTARA-X — Vision-Based Autonomous Navigation

**Beyond Seeing. Into Understanding.** · Team Hack01 · Hack in Hills ’26

Mission: *“Navigate to the target while avoiding obstacles.”*

VISTARA-X is a simulation-first autonomous robot. A simulated robot perceives its surroundings through a rendered camera, plans a collision-free route with A* on an occupancy grid, drives it with a pure-pursuit controller, detects when an obstacle blocks the route, and replans live, all visible on a React dashboard fed by real backend telemetry.

| Team member | Role |
|---|---|
| Ritesh Kumar | Backend and AI/ML Developer |
| Kainat Afrazi | Frontend Developer |

## Problem statement

Autonomous robots need to understand their surroundings, identify relevant objects and people, navigate toward a given objective, and avoid obstacles in real time.

## Architecture

```text
 frontend/ (React + Vite, :5173)                 backend/ (FastAPI, :8000)
 ┌────────────────────────────┐   REST commands   ┌────────────────────────────────────────────┐
 │ Overview / Architecture    │ ────────────────▶ │ api/routes.py  (validated, rate-limited)   │
 │ Live mission dashboard     │                   │        │ locked commands                   │
 │  canvas map, controls,     │ ◀──────────────── │ simulation/engine.py  ── 20 Hz thread ──┐  │
 │  telemetry, perception,    │  WS /ws/telemetry │   mission state machine (decision)      │  │
 │  event log, guided demo    │   10 Hz, versioned│   navigation/grid.py + astar.py (A*)    │  │
 └────────────────────────────┘                   │   control/controller.py (pure pursuit)  │  │
                                                  │   simulation/physics.py (PyBullet check)│  │
                                                  │ perception/service.py ── worker thread ─┘  │
                                                  │   camera (PyBullet render) → detector      │
                                                  │   (YOLOv8 | labelled ground truth)          │
                                                  │   scene/ (class policy, tracks, explored)   │
                                                  └────────────────────────────────────────────┘
```

Loop: **Observe → Detect → Understand → Decide → Plan → Move → Monitor → Replan.**
Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · API: [docs/API.md](docs/API.md) · Judge demo: [docs/DEMO.md](docs/DEMO.md) · Deck mapping: [docs/CONTENT_INVENTORY.md](docs/CONTENT_INVENTORY.md)

### Implemented vs. fallback vs. future

| Capability | Status |
|---|---|
| Deterministic scenarios, robot, static/inserted/moving obstacles | Implemented |
| Occupancy grid with inflation + unknown (unobserved) cells | Implemented |
| A* planning, smoothing, unreachable-target detection | Implemented |
| Pure-pursuit control, safety-stop layer, dynamic replanning, honest Blocked state | Implemented |
| PyBullet collision/contact verification and camera rendering (headless) | Implemented when `pybullet` is installed; analytic 2D fallback otherwise |
| YOLOv8 inference | Implemented when weights exist; labelled ground-truth detector otherwise (default) |
| Real cameras, LiDAR, motors, VLMs, voice objectives, multi-robot | Future scope (not implemented) |

## Prerequisites

- Python 3.10+ and Node.js 20+ (tested: Python 3.10.11, Node 22.12, Windows 11).
- Optional: Microsoft C++ Build Tools (Windows) to compile PyBullet; YOLOv8 weights.

## Install and run (two terminals)

**Terminal 1 — backend**

```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate      # optional
pip install -r requirements.txt
pip install -r requirements-optional.txt           # optional: PyBullet + YOLOv8
copy .env.example .env                             # optional
python -m uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs (disabled when `VISTARA_ENV=production`).

**Terminal 2 — frontend**

```powershell
cd frontend
npm install
copy .env.example .env                             # optional
npm run dev
```

Open http://localhost:5173 → **Live mission**.

## Model weights

Weights are never downloaded automatically and are git-ignored. Place `yolov8n.pt` in `backend/models/` (see `backend/models/README.md`) or set `VISTARA_YOLO_WEIGHTS`. Then choose **YOLOv8 inference** in the Perception panel. Without weights the option is disabled and the panel shows *Simulated (ground truth)*, which reports no confidence score. Note: the camera image is a simple render, so a COCO-trained YOLOv8 often detects nothing in it; results are shown unedited.

## Environment variables

Frontend (`frontend/.env`; every `VITE_*` value is public, never put secrets here):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend URL; WebSocket URL is derived (`https`→`wss`) |
| `VITE_SITE_URL` | empty | Public origin; when set, the build emits `sitemap.xml` and a canonical link |

Backend (`backend/.env`, see `backend/.env.example`): `VISTARA_ENV`, `VISTARA_CORS_ORIGINS`, `VISTARA_DETECTOR`, `VISTARA_YOLO_WEIGHTS`, `VISTARA_YOLO_CONFIDENCE`, `VISTARA_SIM_HZ` (timestep), `VISTARA_TELEMETRY_HZ`, `VISTARA_PERCEPTION_HZ`, `VISTARA_GRID_RESOLUTION`, `VISTARA_MAX_SPEED`, `VISTARA_SAFETY_MARGIN`, `VISTARA_PHYSICS` (`auto|pybullet|analytic`), `VISTARA_PYBULLET_GUI`, `VISTARA_LOG_LEVEL`, `VISTARA_MAX_WS_CLIENTS`. The project has no secrets; none are required.

## Tests

```powershell
cd backend;  python -m pytest                     # unit + API + WebSocket + integration
cd frontend; npm run build                        # production build
# Browser E2E (needs both apps running; Python Playwright + Chromium):
pip install playwright; python -m playwright install chromium
python -m pytest frontend/e2e                     # E2E_BACKEND_URL / E2E_FRONTEND_URL to override
```

## Deployment and security

- CORS and the WebSocket origin check allow only `VISTARA_CORS_ORIGINS`; set it to the exact production frontend origin.
- Production: serve the frontend over HTTPS and set `VITE_API_BASE_URL=https://…` so telemetry uses `wss://`. `VISTARA_ENV=production` adds HSTS and hides `/docs`. HTTPS has **not** been deployed or verified by us.
- POST/DELETE requests are rate-limited per IP (30 per 5 s). All inputs are validated server-side; errors are structured JSON without stack traces.
- No cookies, analytics or third-party scripts are used, so no consent banner is needed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `WinError 10013` / port in use | Another process holds port 8000/5173. Stop it, or use `--port 8010` and set `VITE_API_BASE_URL` accordingly (and add the origin to `VISTARA_CORS_ORIGINS` if the frontend port changes). |
| Dashboard says *Backend unreachable* | Start the backend; the page reconnects automatically. |
| WebSocket closes immediately | The page origin is not in `VISTARA_CORS_ORIGINS`. |
| `pip install pybullet` fails on Windows | Install “Desktop development with C++” build tools, or skip it: the analytic fallback is used and labelled. |
| YOLOv8 option disabled | Weights missing or `ultralytics` not installed. |

## Known limitations

Simulation only; collision avoidance uses ground-truth geometry; robot motion is kinematic (PyBullet is used for collision checks and rendering, not to drive the robot); the target is operator-selected; moving obstacles are not predicted; no accuracy/latency benchmarks are claimed. See the Future scope page.
