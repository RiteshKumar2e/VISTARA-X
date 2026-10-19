# Architecture

## Threads and lifecycle
- **Simulation thread** (`simulation/engine.py`, fixed `1/VISTARA_SIM_HZ` timestep): the only code that moves the robot. API handlers call locked command methods; no second controller can exist.
- **Perception thread**: renders the camera, runs the detector, updates scene understanding. Slow YOLO inference never delays control.
- **Telemetry task** (asyncio): samples snapshots at a fixed rate and fans out through bounded per-client queues.

## Per tick (20 Hz)
1. Move patrolling obstacles (they yield to the robot).
2. Rebuild the occupancy grid if anything changed; sync PyBullet bodies.
3. State machine: `planning` → A*; `navigating` → goal check → route-obstruction check (next 4 m) → replan if blocked → pure-pursuit command (speed limited by perception's person-ahead governor) → safety veto (would clearance drop below 5 cm?) → integrate kinematics.
4. Verify clearance and contacts in PyBullet (or analytic fallback); count collisions.

## Modules
| Folder | Responsibility |
|---|---|
| `backend/app/simulation/` | world model, scenarios, engine/state machine, PyBullet scene/collision/camera |
| `backend/app/navigation/` | occupancy grid (inflation, caution band, cell states), A*, smoothing |
| `backend/app/control/` | pure-pursuit controller, kinematics |
| `backend/app/perception/` | camera rendering (PyBullet or ray cast), detectors (YOLOv8 / ground truth), service |
| `backend/app/scene/` | class→obstacle policy, obstacle tracker, explored-area mask, summary |
| `backend/app/api/` | REST routes, WebSocket hub |
| `frontend/src/simulation/` | canvas renderer |
| `frontend/src/content/deck.js` | all deck-derived copy and implementation statuses |

## Ground truth vs. perception
Planning and collision safety use simulator geometry. Camera detections, tracks and the explored map are for perception visualisation and evaluation; only the person-ahead speed limit uses them, and only while fresh.

## Hardware path (future)
Replace `PyBulletCamera` with a real RGB-D source producing the same `CameraFrame`, replace `integrate()` with motor commands, and replace ground-truth obstacles with perception-built occupancy. Interfaces are kept small for that reason.
