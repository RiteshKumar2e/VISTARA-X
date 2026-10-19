# Judge demo script (about 3 minutes)

Everything below drives the real backend simulation. Start both apps (README), open http://localhost:5173.

## 1. Overview (30 s)
1. On **Overview**, read the problem and mission line. Click step **05 Obstacle detected?** in *How a mission runs* to show the decision branch.
2. Open **Architecture**, click **1.3 YOLO detection**: the status tag says *With labelled fallback* and *Live from the backend* shows the active detector. Click **3.3 Environment feedback** to show the live collision backend (PyBullet) and collision count.

## 2. Guided demo (90 s) — Live mission page
Click **Run guided demo**. Each step completes only when telemetry confirms it:
1. Warehouse scenario loads (robot at 1.5, 6.0).
2. Target (18.5, 6.0) is selected — crosshair on the map.
3. **Start mission** — A* route and waypoints appear; *Last A\* plan* shows length, nodes expanded and planning time.
4. Robot drives (trail, telemetry, camera view update).
5. A barrier is dropped across the route a few metres ahead.
6. Event log: *Route obstructed by user-1; replanning* → *Replanned around user-1*; a notification appears and the route changes on the map.
7. **Goal reached** appears only when the robot is within 0.2 m of the target. Collisions stay 0.

## 3. Manual exploration (60 s)
- **Reset**, then click the map to set a target and **Start mission**. Use **Pause / Resume / Stop**.
- Switch *Map click action* to **Place obstacle** and click on the route while it drives: it replans.
- **Honest failure:** Scenario → *Enclosed bay (unreachable)* → **Load**, set target `16, 6`, **Start mission** → status **Blocked** with “No collision-free route to the target exists”; the robot never moves.
- Perception panel: switch to **YOLOv8 inference** (if weights are present) to show real model output on the rendered frame, including when it finds nothing.

## If something goes wrong
- *Backend unreachable* banner → start/restart the backend; the page reconnects.
- Mission ended Blocked in the warehouse (e.g. the patrolling person sealed a gap) → this is the honest state; click **Restart guided demo**.
