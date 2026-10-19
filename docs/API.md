# VISTARA-X API

Base URL `http://localhost:8000`. Interactive schema: `/docs` (development only).
Errors always look like `{"error": {"code": "...", "message": "...", "details": [...]?}}`.
Codes: `422 validation_error | unknown_scenario | target_out_of_bounds | invalid_mode`, `409 no_target | mission_active | mission_paused | not_running | not_paused | target_unsafe | too_close_to_robot | covers_target | no_active_route | no_space | detector_unavailable`, `404 not_found`, `429 rate_limited`, `500 internal_error`.

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/health` | | Service + subsystem health (simulation/physics, perception, telemetry) |
| GET | `/status` | | Simulation, mission, perception and telemetry status |
| GET | `/map` | | Bounds, obstacles, grid (`blocked` rows; `cells` rows with `#` occupied, `+` inflated, `.` observed free, `?` unknown), target cell |
| GET | `/path` | | Current waypoints, waypoint index, last plan metadata |
| GET | `/detections` | | Perception snapshot: mode, detections, tracks, scene summary |
| GET | `/telemetry` | | Same payload as the WebSocket (for polling/debugging) |
| GET | `/scenarios` | | Available scenarios and default targets |
| GET | `/perception/frame` | | Latest camera JPEG (204 if none) |
| POST | `/target` | `{"x": 18.5, "y": 6}` | Set/update target (replans mid-mission) |
| POST | `/navigate` | `{"target": {"x":..,"y":..}}` optional | Start a mission |
| POST | `/navigation/pause` · `/resume` · `/stop` | | Mission lifecycle |
| POST | `/simulation/reset` | `{"scenario": "warehouse"}` | `warehouse`, `slalom`, `enclosed` |
| POST | `/simulation/config` | `{"max_speed":0.2–1.5,"safety_margin":0.05–0.6,"moving_obstacles":bool}` | Runtime parameters |
| POST | `/obstacles` | `{"x","y","shape":"rect|circle","size":0.3–2,"label"}` | Insert an obstacle |
| POST | `/obstacles/inject` | | Drop a barrier across the active route (leaves a detour) |
| DELETE | `/obstacles` | | Remove inserted obstacles |
| POST | `/perception/mode` | `{"mode": "simulated|yolov8"}` | Switch detector |
| POST | `/perception/config` | `{"enabled","rate_hz":0.5–15,"confidence":0.05–0.95}` | Frame-processing controls |

## WebSocket `/ws/telemetry`

Server → client JSON at `VISTARA_TELEMETRY_HZ` (10 Hz), `type: "telemetry"`, `version: 1`, strictly increasing `seq`. Each client has a queue of size 1 (newest wins). Fields: `sim_time, scenario, mission{id,status,waiting,reason,elapsed,distance_travelled,replans,safety_stops,goal_reached,progress}, robot{x,y,theta,heading_deg,v,w,radius}, target, distance_to_target, path, current_waypoint, remaining_path_length, last_plan, safety{clearance,nearest,warning,collisions,in_contact,inflation,physics}, obstacles, params, events[], perception{mode,source_label,enabled,rate_hz,confidence_threshold,renderer,stale,detections[],tracks[],scene,explored}`. The JSDoc contract is in `frontend/src/types/telemetry.js`.

Client → server: only `{"type":"ping"}` (answered with `pong`); anything else gets `{"type":"error","code":"invalid_message"}`. Connections from origins outside `VISTARA_CORS_ORIGINS` are closed (1008).
