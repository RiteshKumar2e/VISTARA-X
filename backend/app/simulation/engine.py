"""Simulation engine and mission state machine.

One engine thread owns the robot: it advances the world at a fixed timestep and is
the only place control commands are produced, so concurrent controllers cannot
fight over the robot. API handlers only mutate state through the locked command
methods below. A second worker thread runs perception (camera + detector).
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..control.controller import PurePursuitController, integrate
from ..mapping.occupancy import FREE, OCCUPIED, UNKNOWN, LogOddsMap, resample
from ..mapping.slam import SlamSession
from ..navigation.astar import plan
from ..navigation.grid import OccupancyGrid

import numpy as np
from scipy.ndimage import label as label_regions
from ..perception.service import PerceptionService
from ..prediction.risk import predicted_mask
from ..prediction.system import PredictionSystem
from ..operations.manager import OperationsManager
from ..sensors.suite import SensorSuite
from .physics import PYBULLET_AVAILABLE, PYBULLET_ERROR, AnalyticCollision, PyBulletCollision
from .scenarios import DEFAULT_SCENARIO, MAP_H, MAP_W, SCENARIOS
from .world import ROBOT_RADIUS, Obstacle, World

log = logging.getLogger("vistara.engine")

TELEMETRY_VERSION = 1
GOAL_TOLERANCE = 0.2  # metres
OBSTRUCTION_LOOKAHEAD = 4.0  # metres of route checked every tick
REPLAN_COOLDOWN = 0.5  # seconds
STOP_DISTANCE = 0.05  # emergency stop if clearance would drop below this
WARNING_CLEARANCE = 0.10  # collision warning threshold (surface to surface)
MOVING_EXTRA_INFLATION = 0.25
BLOCKED_RETRY_WINDOW = 8.0  # seconds to wait for moving obstacles to clear
BLOCKED_RETRY_PERIOD = 1.0
MAX_USER_OBSTACLES = 30

ACTIVE = {"planning", "navigating", "replanning", "blocked_waiting"}
REPLAN_DWELL = 0.3  # seconds the robot holds still after a route is invalidated, before replanning
SLAM_RESOLUTION = 0.1  # m per mapping cell
PLANNER_MAPS = ("simulator", "slam", "imported")
MIN_FRONTIER_CELLS = 6  # frontier clusters smaller than this (0.6 m) are ignored
MAX_EXPLORE_GOALS = 30
MAP_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
DOOR_SPEED = 0.9  # m/s a sliding door panel moves
DOOR_TRIGGER_ROBOT = 2.0  # m: a door opens when the robot is this close
DOOR_TRIGGER_PERSON = 1.6
DOOR_CLOSE_AFTER = 2.5  # s with nobody near before a door closes
ZONE_LOOKAHEAD = 1.0  # m of route ahead checked against speed zones
PRED_SPEEDUP_HOLD = 0.6  # s a lower predictive speed is held before speeding up again
PRED_REPLAN_AFTER = 2.5  # s of waiting before trying a route around the predicted path
PRED_REPLAN_COOLDOWN = 3.0  # s between predictive replans


class CommandError(Exception):
    """Raised by engine commands; mapped to structured HTTP errors by the API."""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class SimulationEngine:
    def __init__(self, settings: Settings, perception: PerceptionService | None = None):
        self.settings = settings
        self.dt = 1.0 / settings.sim_hz
        self.grid_resolution = settings.grid_resolution
        self.perception = perception or PerceptionService(settings, (MAP_W, MAP_H))
        self.physics = self._make_physics(settings)
        res = settings.grid_resolution
        self.sensors = SensorSuite((int(math.ceil(MAP_H / res)), int(math.ceil(MAP_W / res))), res)
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._running = threading.Event()
        self.params = {
            "max_speed": settings.max_speed,
            "safety_margin": settings.safety_margin,
            "moving_obstacles": True,
            "planner_map": "simulator",
            "predictive": True,
        }
        self.prediction = PredictionSystem()
        self._extra_block = None  # temporary predicted-path cells used for one replan
        self._evade_target = None  # point the robot steps aside to when an object heads for it
        self.slam = SlamSession(MAP_W, MAP_H, SLAM_RESOLUTION)
        self.imported_map: dict | None = None  # {"map": LogOddsMap, "name", "source", "meta"}
        self.maps_dir = Path(settings.maps_dir)
        self._grid_source_version = None
        self.controller = PurePursuitController()
        self.events: deque[dict] = deque(maxlen=200)
        self._event_id = 0
        self.seq = 0
        self.thread_alive = False
        self.operations = OperationsManager(self, Path(settings.ops_dir), settings.webhook_url)
        self.reset(DEFAULT_SCENARIO, log_event=False)
        self._event("info", "system", "Simulation initialised")

    @staticmethod
    def _make_physics(settings: Settings):
        """PyBullet collision checking when available, else the analytic fallback."""
        if settings.physics != "analytic" and PYBULLET_AVAILABLE:
            try:
                return PyBulletCollision(MAP_W, MAP_H, gui=settings.pybullet_gui)
            except Exception as exc:  # pragma: no cover - environment specific
                log.warning("PyBullet unavailable (%s); using analytic collision", exc)
        elif settings.physics == "pybullet":
            raise RuntimeError(f"VISTARA_PHYSICS=pybullet but {PYBULLET_ERROR}")
        return AnalyticCollision(MAP_W, MAP_H)

    # ================================================================ lifecycle
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        for target, name in ((self._sim_loop, "sim"), (self._perception_loop, "perception")):
            t = threading.Thread(target=target, name=f"vistara-{name}", daemon=True)
            t.start()
            self._threads.append(t)

    def shutdown(self) -> None:
        self._running.clear()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        self.thread_alive = False
        self.physics.close()
        self.perception.close()

    def _sim_loop(self) -> None:
        self.thread_alive = True
        next_t = time.monotonic()
        while self._running.is_set():
            try:
                self.step()
            except Exception:  # never let the loop die silently
                log.exception("Simulation step failed")
                with self._lock:
                    if self.status in ACTIVE or self.status == "paused":
                        self._halt("error", "Internal simulation error - mission halted (see server log)")
                    self._event("error", "error", "Internal simulation error (see server log)")
            next_t += self.dt
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.25:  # fell far behind: resync instead of spiralling
                next_t = time.monotonic()
        self.thread_alive = False

    def _perception_loop(self) -> None:
        while self._running.is_set():
            started = time.monotonic()
            with self._lock:
                pose = (self.world.robot.x, self.world.robot.y, self.world.robot.theta)
                obstacles = [o.copy() for o in self.world.obstacles]
                w, h = self.world.width, self.world.height
                sim_time = self.sim_time
            try:
                error = self.perception.process(pose, obstacles, w, h, sim_time)
                if error:
                    with self._lock:
                        self._event("warning", "perception", error)
            except Exception:
                log.exception("Perception step failed")
            time.sleep(max(0.0, self.perception.period - (time.monotonic() - started)))

    # ================================================================ helpers
    def _event(self, level: str, kind: str, message: str, **data) -> None:
        self._event_id += 1
        self.events.append(
            {
                "id": self._event_id,
                "sim_time": round(self.sim_time, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "level": level,
                "type": kind,
                "message": message,
                **({"data": data} if data else {}),
            }
        )
        log.info("[%s] %s", kind, message)

    @property
    def inflation(self) -> float:
        return ROBOT_RADIUS + self.params["safety_margin"]

    def _planner_source_map(self) -> LogOddsMap | None:
        src = self.params["planner_map"]
        if src == "slam":
            return self.slam.map
        if src == "imported" and self.imported_map:
            return self.imported_map["map"]
        return None

    def _rebuild_grid(self) -> None:
        source = self._planner_source_map()
        if source is None:
            # Doors are passable for planning: the robot opens them on approach. Physics,
            # LiDAR and the safety veto still treat a closed door as solid.
            self.grid.build([o for o in self.world.obstacles if o.label != "door"], self.inflation, MOVING_EXTRA_INFLATION)
        else:
            occ, unknown = resample(
                source.states(), source.resolution, source.origin, self.grid.rows, self.grid.cols, self.grid.resolution
            )
            imported = self.params["planner_map"] == "imported"
            if imported:
                # An imported map is static: obstacles that are not in it (people, added
                # objects) come from live LiDAR returns of the last 2 s.
                occ = occ | self.sensors.lidar_occupied(self.sim_time)
            self.grid.build_from_mask(occ, unknown, self.inflation, unknown_blocked=imported)
            self._grid_source_version = (source.version, self.sensors.lidar.seq)
        if self._extra_block is not None:
            self.grid.blocked |= self._extra_block
        self.physics.sync(self.world.obstacles)
        self._grid_dirty = False

    def _verify_collisions(self) -> None:
        """Authoritative clearance/contact check against the physics geometry."""
        r = self.world.robot
        self.clearance, self.nearest_obstacle = self.physics.clearance(r.x, r.y)
        self.contacts = self.physics.contacts()

    def _halt(self, status: str, reason: str = "") -> None:
        self.status = status
        self.status_reason = reason
        self.world.robot.v = 0.0
        self.world.robot.w = 0.0

    def _plan(self, cause: str) -> bool:
        if self._grid_dirty:
            self._rebuild_grid()
        r = self.world.robot
        started = time.perf_counter()
        result = plan(self.grid, (r.x, r.y), self.target)
        self.last_plan_ms = round((time.perf_counter() - started) * 1000, 2)
        self.last_replan_time = self.sim_time
        self.plan_count += 1
        if not result.success:
            self.path = []
            self.last_plan = {"success": False, "reason": result.reason, "expanded": result.expanded}
            return False
        valid, checked = self._validate_route(result.waypoints)
        if not valid:
            # Defensive double-check failed: never drive a route that crosses unsafe cells.
            self.path = []
            self.last_plan = {"success": False, "reason": "validation_failed", "expanded": result.expanded}
            return False
        self.path = result.waypoints
        self.waypoint_index = 1
        self.path_version += 1
        self.last_plan = {
            "success": True,
            "cause": cause,
            "expanded": result.expanded,
            "grid_cells": len(result.cells),
            "waypoints": len(result.waypoints),
            "length": round(result.length, 2),
            "planning_ms": self.last_plan_ms,
            "validated": True,
            "checked_samples": checked,
        }
        return True

    def _validate_route(self, points) -> tuple[bool, int]:
        """Independent check of a planned route: every sampled point along every segment
        must lie in a free (non-inflated) cell of the current grid. Samples under the
        robot's own footprint are skipped (the robot may start inside a safety band)."""
        r = self.world.robot
        step = self.grid_resolution * 0.5
        checked = 0
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            n = max(int(math.hypot(bx - ax, by - ay) / step), 1)
            for i in range(n + 1):
                px, py = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
                if math.hypot(px - r.x, py - r.y) < ROBOT_RADIUS + 0.05:
                    continue
                checked += 1
                row, col = self.grid.world_to_cell(px, py)
                if self.grid.blocked[row, col]:
                    return False, checked
        return True, checked

    def _record_replan(self, cause: str, obstacle: str | None, outcome: str, previous: float | None) -> None:
        lp = self.last_plan or {}
        self.replan_history.append({
            "sim_time": round(self.sim_time, 2),
            "cause": cause,
            "obstacle": obstacle,
            "outcome": outcome,
            "previous_length": previous,
            "new_length": lp.get("length") if lp.get("success") else None,
            "planning_ms": lp.get("planning_ms") if lp.get("success") else None,
            "validated": bool(lp.get("validated")),
        })

    def _route_length(self) -> float | None:
        if len(self.path) < 2:
            return None
        return round(sum(math.dist(a, b) for a, b in zip(self.path, self.path[1:])), 2)

    def _begin_replan(self, cause: str, obstacle: str | None) -> None:
        """Route invalidated: stop the robot, then replan after a short dwell."""
        self._replan = {"cause": cause, "obstacle": obstacle, "since": self.sim_time, "previous": self._route_length()}
        self.status = "replanning"
        self.status_reason = f"Route invalidated by {obstacle or 'a change in the map'}; replanning"
        self.world.robot.v = self.world.robot.w = 0.0

    def _step_replanning(self) -> None:
        rp = self._replan
        if self.sim_time - rp["since"] < REPLAN_DWELL:
            return  # holding still while the map settles
        name = rp["obstacle"] or "map change"
        if self._plan(rp["cause"]):
            self.status = "navigating"
            self.status_reason = ""
            self.replans += 1
            self._record_replan(rp["cause"], rp["obstacle"], "replanned", rp["previous"])
            lp = self.last_plan
            self._event(
                "info",
                "replanned",
                f"Replanned around {name}: {lp['length']:.1f} m, {lp['waypoints']} waypoints "
                f"({lp['planning_ms']:.1f} ms); route validated ({lp['checked_samples']} samples clear)",
                obstacle=name,
            )
        else:
            self._record_replan(rp["cause"], rp["obstacle"], "blocked", rp["previous"])
            self._enter_blocked(self.last_plan["reason"])

    def _path_obstruction(self) -> Obstacle | None | bool:
        """Sample the planned route for the next few metres ahead of the robot.
        Returns the blocking obstacle (or True for a boundary block) if the route
        now crosses an unsafe cell. Only the planned polyline is checked, so the
        controller's normal corner-cutting does not trigger false replans."""
        if len(self.path) < 2:
            return None
        r = self.world.robot
        start = max(self.waypoint_index - 1, 0)
        step = self.grid_resolution * 0.5
        travelled = 0.0
        for k in range(start, len(self.path) - 1):
            (ax, ay), (bx, by) = self.path[k], self.path[k + 1]
            seg = math.hypot(bx - ax, by - ay)
            if seg < 1e-9:
                continue
            # On the current segment, begin at the robot's projection.
            t0 = 0.0
            if k == start:
                t0 = max(0.0, min(1.0, ((r.x - ax) * (bx - ax) + (r.y - ay) * (by - ay)) / seg**2))
            n = max(int(seg * (1 - t0) / step), 1)
            for i in range(1, n + 1):
                t = t0 + (1 - t0) * i / n
                px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                if travelled + seg * (t - t0) > OBSTRUCTION_LOOKAHEAD:
                    return None
                if math.hypot(px - r.x, py - r.y) < ROBOT_RADIUS + 0.05:
                    continue  # ignore the cells under the robot itself
                row, col = self.grid.world_to_cell(px, py)
                if self.grid.blocked[row, col]:
                    if self.params["planner_map"] != "simulator":
                        return True  # a mapped obstacle: the map has no object identities
                    return self._blocking_obstacle(px, py) or True
            travelled += seg * (1 - t0)
        return None

    def _blocking_obstacle(self, px: float, py: float) -> Obstacle | None:
        """Which obstacle makes the cell at (px, py) unsafe. Cells are blocked by their
        centre, so allow up to one cell diagonal of slack; None means the map edge."""
        reach = self.inflation + self.grid_resolution * 0.75
        best, best_d = None, float("inf")
        for o in self.world.obstacles:
            if o.label == "door":
                continue
            d = float(o.distance(px, py)) - (MOVING_EXTRA_INFLATION if o.moving else 0.0)
            if d < reach and d < best_d:
                best, best_d = o, d
        return best

    def _move_obstacles(self) -> None:
        if not self.params["moving_obstacles"]:
            return
        r = self.world.robot
        for obs in self.world.obstacles:
            if not obs.moving:
                continue
            tx, ty = obs.patrol[obs.patrol_index]
            dx, dy = tx - obs.x, ty - obs.y
            dist = math.hypot(dx, dy)
            if dist < 0.05:
                obs.patrol_index = (obs.patrol_index + 1) % len(obs.patrol)
                continue
            stepd = min(obs.speed * self.dt, dist)
            nx, ny = obs.x + dx / dist * stepd, obs.y + dy / dist * stepd
            # People normally yield to the robot and never step into its safety bubble;
            # obstacles with yields=False keep walking (the predictive layer must avoid them).
            if obs.yields and math.hypot(nx - r.x, ny - r.y) < obs.r + ROBOT_RADIUS + 0.35:
                continue
            obs.x, obs.y = nx, ny
            self._grid_dirty = True

    # ================================================================ step
    def step(self) -> None:
        with self._lock:
            self.seq += 1
            if self.status == "paused":
                return
            self.sim_time += self.dt
            self._update_doors()
            if self.status in ACTIVE:
                self.mission_time += self.dt
                self._move_obstacles()
            if self._grid_dirty:
                self._rebuild_grid()

            if self.status == "planning":
                self._step_planning()
            elif self.status == "navigating":
                self._step_navigating()
            elif self.status == "replanning":
                self._step_replanning()
            elif self.status == "blocked_waiting":
                self._step_blocked_waiting()

            self.sensors.step(self.world, self.dt, self.sim_time)
            r = self.world.robot
            odom = self.sensors.odometry
            self.slam.step(
                tuple(odom._pose) if odom.enabled and odom._pose is not None else None,
                self.sensors.lidar,
                (r.x, r.y, r.theta),
                self.sim_time,
            )
            self.prediction.on_tick(self.world, self.sensors.lidar, self.sim_time,
                                    lambda: self.perception.camera_tracks(self.sim_time))
            if self.status != "navigating":
                self.prediction.idle({
                    "replanning": "Robot stopped while the route is replanned",
                    "planning": "Planning a route",
                    "blocked_waiting": "Waiting for a route to clear",
                    "paused": "Mission paused",
                }.get(self.status, "No active route"))
            source = self._planner_source_map()
            if source is not None and self._grid_source_version != (source.version, self.sensors.lidar.seq):
                self._grid_dirty = True  # the map (or the live LiDAR layer) changed
            self._verify_collisions()
            warning = self.clearance < WARNING_CLEARANCE
            if warning and not self.collision_warning:
                self._event(
                    "warning",
                    "collision_warning",
                    f"Clearance {max(self.clearance, 0):.2f} m to {self.nearest_obstacle}",
                )
            self.collision_warning = warning
            in_collision = self.clearance <= 0 or bool(self.contacts)
            if in_collision and not self._in_collision:
                self.collisions += 1
                what = ", ".join(self.contacts) or self.nearest_obstacle
                self._event("error", "collision", f"Contact with {what}")
                if self.status in ACTIVE:
                    self._halt("stopped", f"Collision with {what}; robot halted")
            self._in_collision = in_collision
            self.operations.tick()

    def _step_planning(self) -> None:
        if self.exploring and self.target is None:
            if self.slam.map.scans >= 3:
                self._explore_next()
            return
        causes = {
            "mission_start": "Planning route with A*",
            "target_changed": "Target changed; planning a new route with A*",
            "resume": "Planning route from the current pose with A*",
            "explore": "Planning a route to the next frontier with A*",
        }
        self._event("info", "planning", causes.get(self._plan_cause, "Planning route with A*"))
        if self._plan(self._plan_cause):
            self.status = "navigating"
            self.status_reason = ""
            lp = self.last_plan
            self._event(
                "info",
                "route_planned",
                f"A* route: {lp['length']:.1f} m, {lp['waypoints']} waypoints "
                f"({lp['expanded']} nodes expanded, {lp['planning_ms']:.1f} ms)",
                length=lp["length"],
            )
        else:
            self._enter_blocked(self.last_plan["reason"])

    def _enter_blocked(self, reason: str) -> None:
        if self.exploring:
            # An unreachable frontier is skipped, not reported as a failed mission.
            self._explore_blacklist.append(self.target)
            self._event("info", "explore", "Frontier unreachable; choosing another")
            self._explore_next()
            return
        messages = {
            "no_path": "No collision-free route to the target exists",
            "goal_blocked": "Target lies inside an obstacle's safety zone",
            "start_blocked": "Robot is boxed in; no free cell to start from",
        }
        text = messages.get(reason, reason)
        moving = self.params["moving_obstacles"] and any(o.moving for o in self.world.obstacles)
        self.world.robot.v = self.world.robot.w = 0.0
        if moving:
            self.status = "blocked_waiting"
            self.status_reason = f"{text}; waiting for moving obstacles to clear"
            self._blocked_since = self.sim_time
            self._event("warning", "blocked", self.status_reason)
        else:
            self._halt("blocked", text)
            self._event("error", "blocked", f"Mission blocked: {text}. Robot stopped safely.")

    def _step_blocked_waiting(self) -> None:
        if self.sim_time - self.last_replan_time < BLOCKED_RETRY_PERIOD:
            return
        if self._plan("retry"):
            self.status = "navigating"
            self.status_reason = ""
            self.replans += 1
            self._record_replan("retry", None, "replanned", None)
            self._event("success", "replanned", "Route cleared; resuming on new route")
        elif self.sim_time - self._blocked_since >= BLOCKED_RETRY_WINDOW:
            self._halt("blocked", "No collision-free route found after waiting")
            self._event("error", "blocked", "Mission blocked: no route after waiting. Robot stopped.")

    def _step_navigating(self) -> None:
        r = self.world.robot
        tx, ty = self.target
        if math.hypot(tx - r.x, ty - r.y) <= GOAL_TOLERANCE:
            if self.exploring:
                self._explore_blacklist.append(self.target)
                self._explore_next()
                return
            self._halt("goal_reached", "")
            self._event(
                "success",
                "goal_reached",
                f"Goal reached in {self.mission_time:.1f} s after {self.distance_travelled:.1f} m "
                f"and {self.replans} replan(s)",
            )
            return

        # While stepping aside the robot is off its route, so the route check does not apply.
        blocker = self._path_obstruction() if self._evade_target is None else None
        if blocker is not None and self.sim_time - self.last_replan_time >= REPLAN_COOLDOWN:
            if isinstance(blocker, Obstacle):
                name = blocker.id
            elif self.params["planner_map"] == "simulator":
                name = "map edge"
            else:
                name = f"an obstacle in the {self.params['planner_map']} map"
            self._event("warning", "obstruction", f"Route obstructed by {name}; robot stopped, replanning", obstacle=name)
            self._begin_replan("obstruction", name)
            return

        pred_factor, waiting = self._predictive_step(r)
        if self.status != "navigating":
            return  # a predictive replan changed the state

        speed_factor = self.perception.fresh_summary().get("speed_factor", 1.0)
        if speed_factor < 1.0 and not self._slowed:
            self._event("info", "perception", "Person detected ahead; speed reduced by 50%")
        self._slowed = speed_factor < 1.0

        # Measured proximity (simulated LiDAR + ultrasonic) in the driving corridor,
        # up to the waypoint the robot is heading for.
        wp = self.path[min(self.waypoint_index, len(self.path) - 1)]
        corridor = max(math.hypot(wp[0] - r.x, wp[1] - r.y), 0.5)
        prox = self.sensors.proximity(r, corridor)
        if prox["action"] != self._prox_action:
            src = "+".join(prox["sources"])
            dist = prox["front_clearance"]
            msg = {
                "slow": lambda: f"Proximity: {dist:.2f} m ahead ({src}); slowing down",
                "stop": lambda: f"Proximity stop: {dist:.2f} m ahead ({src})",
                "degraded": lambda: "No fresh proximity sensor (LiDAR/ultrasonic); fail-safe reduced speed",
                "clear": lambda: "Proximity clear; normal speed",
            }[prox["action"]]()
            level = {"stop": "warning", "degraded": "warning"}.get(prox["action"], "info")
            if prox["action"] != "clear" or self._prox_action in ("stop", "degraded"):
                self._event(level, "proximity", msg, sources=prox["sources"])
            self._prox_action = prox["action"]
        speed_factor = min(speed_factor, prox["speed_factor"], pred_factor)
        zone_speed, zone_name = self._zone_limit(r)
        if zone_name != self.zone:
            if zone_name:
                self._event("info", "zone", f"Entering {zone_name}: speed limited to {zone_speed:.2f} m/s")
            self.zone = zone_name
        if zone_speed is not None and self.params["max_speed"] > 0:
            speed_factor = min(speed_factor, zone_speed / self.params["max_speed"])

        self.controller.max_speed = self.params["max_speed"]
        if self._evade_target is not None:
            # Step aside: drive straight to the evade point, then hold there.
            ex, ey = self._evade_target
            if math.hypot(ex - r.x, ey - r.y) > 0.1:
                cmd = self.controller.compute(r, [(r.x, r.y), (ex, ey)], 0, self.dt,
                                              min(self.params["max_speed"], 0.5) * max(prox["speed_factor"], 0.05))
            else:
                cmd = self.controller.compute(r, [(r.x, r.y), (ex, ey)], 0, self.dt, 0.0)
                cmd.v = 0.0
        else:
            cmd = self.controller.compute(
                r, self.path, max(self.waypoint_index - 1, 0), self.dt,
                self.params["max_speed"] * max(speed_factor, 0.05),
            )
            self.waypoint_index = max(self.waypoint_index, cmd.segment_index)
        v, w = cmd.v, cmd.w
        if waiting:
            v = 0.0  # predictive wait/stop: hold position until the conflict clears
        if prox["action"] == "stop" and v > 0:
            # Sensor-triggered stop: no forward motion; turning in place is allowed.
            v = 0.0
            self.proximity_stops += 1
            if self.sim_time - self.last_replan_time >= REPLAN_COOLDOWN * 2:
                previous = self._route_length()
                if self._plan("proximity"):
                    self.replans += 1
                    self._record_replan("proximity", None, "replanned", previous)
                    self._event("info", "replanned", "Replanned after proximity stop; new route validated against the grid")
                else:
                    self._record_replan("proximity", None, "blocked", previous)
                    self._enter_blocked(self.last_plan["reason"])
                    return

        # Safety layer: veto motion that would bring the footprint into contact.
        nx, ny, nth = integrate(r, v, w, self.dt)
        current_clear = self.world.clearance(r.x, r.y)[0] - ROBOT_RADIUS
        next_clear = self.world.clearance(nx, ny)[0] - ROBOT_RADIUS
        if next_clear < STOP_DISTANCE and next_clear < current_clear:
            v = 0.0
            nx, ny, nth = integrate(r, 0.0, w, self.dt)  # rotating in place is safe
            self.safety_stops += 1
            if self.sim_time - self.last_replan_time >= REPLAN_COOLDOWN:
                self._event("warning", "safety_stop", "Safety stop: obstacle too close; replanning")
                if self._plan("safety_stop"):
                    self.replans += 1
                else:
                    self._enter_blocked(self.last_plan["reason"])
                    return

        self.distance_travelled += math.hypot(nx - r.x, ny - r.y)
        r.x, r.y, r.theta, r.v, r.w = nx, ny, nth, v, w

    # ================================================================ commands
    def reset(self, scenario: str = DEFAULT_SCENARIO, log_event: bool = True) -> None:
        if scenario not in SCENARIOS:
            raise CommandError("unknown_scenario", f"Unknown scenario '{scenario}'", 422)
        with self._lock:
            self.scenario = SCENARIOS[scenario]
            self.world: World = self.scenario.build()
            self.grid = OccupancyGrid(self.world.width, self.world.height, self.grid_resolution)
            self._grid_dirty = True
            self._rebuild_grid()
            self.status = "idle"
            self.status_reason = ""
            self.target: tuple[float, float] | None = None
            self.path: list[tuple[float, float]] = []
            self.path_version = 0
            self.waypoint_index = 0
            self.sim_time = 0.0
            self.mission_time = 0.0
            self.distance_travelled = 0.0
            self.replans = 0
            self.plan_count = 0
            self.safety_stops = 0
            self.collisions = 0
            self.collision_warning = False
            self._in_collision = False
            self._slowed = False
            self.contacts: list[str] = []
            self._verify_collisions()
            self.sensors.reset()
            r0 = self.world.robot
            self.slam.reset((r0.x, r0.y, r0.theta))
            self.exploring = False
            self._explore_blacklist: list = []
            self.explore_goals = 0
            self._grid_source_version = None
            self._prox_action = "clear"
            self.prediction.reset(self.world)
            self._init_doors()
            self.zone = None
            self.operations.reset()
            self._pred_factor = 1.0
            self._pred_hold_until = 0.0
            self._pred_action = "continue"
            self._pred_wait_since = None
            self._pred_last_replan = -1e9
            self._extra_block = None
            self._evade_target = None
            self.replan_history: deque = deque(maxlen=20)
            self._replan = None
            self.proximity_stops = 0
            self.last_plan: dict | None = None
            self.last_plan_ms: float | None = None
            self.last_replan_time = -1e9
            self._blocked_since = 0.0
            self._plan_cause = "mission_start"
            self._paused_from = None
            self._user_obstacles = 0
            self.mission_id = 0
            self.events.clear()
            self.perception.clear()
            if log_event:
                self._event("info", "reset", f"Simulation reset: {self.scenario.name}")

    def _validate_target(self, x: float, y: float) -> None:
        w = self.world
        m = self.inflation
        if not (m <= x <= w.width - m and m <= y <= w.height - m):
            raise CommandError(
                "target_out_of_bounds",
                f"Target must be within {m:.2f} m of the map interior "
                f"(x {m:.2f}-{w.width - m:.2f}, y {m:.2f}-{w.height - m:.2f})",
                422,
            )
        if self.params["planner_map"] != "simulator":
            if self._grid_dirty:
                self._rebuild_grid()
            row, col = self.grid.world_to_cell(x, y)
            src = self.params["planner_map"]
            if self.grid.occupied[row, col]:
                what = "outside the known area of" if src == "imported" else "on an obstacle in"
                raise CommandError("target_unsafe", f"Target is {what} the {src} map", 409)
            if self.grid.blocked[row, col]:
                raise CommandError(
                    "target_unsafe", f"Target is too close to an obstacle in the {src} map (needs {m:.2f} m clearance)", 409
                )
            return
        for obs in w.obstacles:
            if obs.moving or obs.label == "door":
                continue
            if float(obs.distance(x, y)) < m:
                raise CommandError(
                    "target_unsafe",
                    f"Target is inside or too close to {obs.id} (needs {m:.2f} m clearance)",
                    409,
                )

    def preview_route(self, x: float, y: float) -> dict:
        """Validate a destination and plan a route to it without moving the robot."""
        with self._lock:
            try:
                self._validate_target(x, y)
            except CommandError as exc:
                return {"valid": False, "reachable": False, "length": None, "code": exc.code, "message": exc.message,
                        "planner_map": self.params["planner_map"]}
            if self._grid_dirty:
                self._rebuild_grid()
            r = self.world.robot
            result = plan(self.grid, (r.x, r.y), (x, y))
            return {
                "valid": True,
                "reachable": result.success,
                "length": round(result.length, 2) if result.success else None,
                "code": "ok" if result.success else result.reason,
                "message": "Route found" if result.success else "No collision-free route exists right now",
                "planner_map": self.params["planner_map"],
            }

    def set_target(self, x: float, y: float) -> None:
        with self._lock:
            self._validate_target(x, y)
            self.target = (round(x, 3), round(y, 3))
            self._event("info", "target", f"Target set to ({x:.2f}, {y:.2f})")
            if self.status in ACTIVE:
                self._plan_cause = "target_changed"
                self.status = "planning"
            elif self.status == "paused":
                self._plan_cause = "target_changed"
                self._paused_from = "planning"
                self.path = []
            else:
                self.path = []
                if self.status != "idle":
                    self.status = "idle"
                    self.status_reason = ""

    def navigate(self) -> None:
        with self._lock:
            if self.target is None:
                raise CommandError("no_target", "Select a target before starting a mission")
            if self.status in ("planning", "navigating", "blocked_waiting"):
                raise CommandError("mission_active", "A mission is already running")
            if self.status == "paused":
                raise CommandError("mission_paused", "Mission is paused; resume or stop it first")
            self.exploring = False
            self.mission_id += 1
            self.mission_time = 0.0
            self.distance_travelled = 0.0
            self.replans = 0
            self.safety_stops = 0
            self._plan_cause = "mission_start"
            self.status = "planning"
            self.status_reason = ""
            self._event("info", "mission", f"Mission {self.mission_id} started")

    def pause(self) -> None:
        with self._lock:
            if self.status not in ACTIVE:
                raise CommandError("not_running", "No running mission to pause")
            self._paused_from = self.status
            self.status = "paused"
            self.world.robot.v = self.world.robot.w = 0.0
            self._event("info", "mission", "Mission paused")

    def resume(self) -> None:
        with self._lock:
            if self.status != "paused":
                raise CommandError("not_paused", "Mission is not paused")
            # The world may have changed while paused: always replan from here.
            self._plan_cause = "resume"
            self.status = "planning"
            self._event("info", "mission", "Mission resumed; replanning from current pose")

    def stop(self) -> None:
        with self._lock:
            if self.status not in ACTIVE and self.status != "paused":
                raise CommandError("not_running", "No active mission to stop")
            self.exploring = False
            self._halt("stopped", "Stopped by operator")
            self._event("info", "mission", "Mission stopped by operator; robot halted")

    def emergency_stop(self) -> str:
        """Halt the robot unconditionally. Never raises: an emergency stop must not fail
        because no mission happens to be running."""
        with self._lock:
            self.exploring = False
            if self.operations.auto_dispatch:
                # An emergency stop also stops the delivery queue until an operator restarts it.
                self.operations.auto_dispatch = False
                self._event("warning", "operations", "Delivery queue paused by the emergency stop")
            if self.status in ACTIVE or self.status == "paused":
                self._halt("stopped", "Emergency stop")
                self._event("warning", "mission", "Emergency stop: robot halted")
                return "Emergency stop: robot halted"
            self.world.robot.v = self.world.robot.w = 0.0
            self._event("info", "mission", "Emergency stop pressed; the robot was not moving")
            return "Emergency stop: the robot was not moving"

    def configure(self, max_speed=None, safety_margin=None, moving_obstacles=None, predictive=None) -> None:
        with self._lock:
            changes = []
            if max_speed is not None:
                self.params["max_speed"] = float(max_speed)
                changes.append(f"max speed {max_speed:.2f} m/s")
            if safety_margin is not None:
                self.params["safety_margin"] = float(safety_margin)
                self._grid_dirty = True
                changes.append(f"safety margin {safety_margin:.2f} m")
            if moving_obstacles is not None:
                self.params["moving_obstacles"] = bool(moving_obstacles)
                changes.append(f"moving obstacles {'on' if moving_obstacles else 'off'}")
            if predictive is not None:
                self.params["predictive"] = bool(predictive)
                changes.append("predictive avoidance " + ("on" if predictive else "off (reactive baseline)"))
            if changes:
                self._event("info", "config", "Parameters updated: " + ", ".join(changes))

    def move_obstacle(self, obstacle_id: str, x: float, y: float) -> dict:
        """Move an operator-added obstacle. Scenario obstacles cannot be moved."""
        with self._lock:
            obs = next((o for o in self.world.obstacles if o.id == obstacle_id), None)
            if obs is None:
                raise CommandError("not_found", f"No obstacle '{obstacle_id}'", 404)
            if not obstacle_id.startswith("user-"):
                raise CommandError("not_movable", "Only obstacles you added can be moved")
            old = (obs.x, obs.y)
            obs.x, obs.y = x, y
            try:
                self._check_new_obstacle(obs, count_limit=False)
            except CommandError:
                obs.x, obs.y = old
                raise
            self._grid_dirty = True
            self._event("warning", "obstacle", f"Obstacle {obstacle_id} moved to ({x:.2f}, {y:.2f})")
            return obs.to_dict()

    def _check_new_obstacle(self, obs: Obstacle, count_limit: bool = True) -> None:
        r = self.world.robot
        if not self.world.in_bounds(obs.x, obs.y):
            raise CommandError("out_of_bounds", "Obstacle must be inside the map", 422)
        if float(obs.distance(r.x, r.y)) < ROBOT_RADIUS + 0.4:
            raise CommandError("too_close_to_robot", "Obstacle would overlap the robot")
        if self.target and float(obs.distance(*self.target)) < ROBOT_RADIUS + 0.2:
            raise CommandError("covers_target", "Obstacle would cover the target")
        # Reject stacking (centre on or inside another obstacle); touching is allowed.
        for other in self.world.obstacles:
            if other.id != obs.id and float(other.distance(obs.x, obs.y)) < 0.1:
                raise CommandError("overlaps_obstacle", f"Obstacle would overlap {other.id}")
        if count_limit and self._user_obstacles >= MAX_USER_OBSTACLES:
            raise CommandError("too_many_obstacles", f"At most {MAX_USER_OBSTACLES} added obstacles")

    PERSON_RADIUS = 0.3
    PERSON_SPEED = 0.45  # m/s walking pace

    def _validate_walk(self, a: tuple, b: tuple) -> None:
        """A walking person's route must stay clear of static geometry and the map edge."""
        length = math.dist(a, b)
        if length < 1.0:
            raise CommandError("invalid_patrol", "A walking route must be at least 1 m long", 422)
        r = self.PERSON_RADIUS
        for i in range(int(length / 0.1) + 1):
            t = i / max(int(length / 0.1), 1)
            px, py = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            if not (r <= px <= self.world.width - r and r <= py <= self.world.height - r):
                raise CommandError("invalid_patrol", "The walking route leaves the map", 422)
            for o in self.world.obstacles:
                if not o.moving and float(o.distance(px, py)) < r + 0.05:
                    raise CommandError("invalid_patrol", f"The walking route passes through {o.id}", 422)

    def add_obstacle(self, x: float, y: float, shape: str = "rect", size: float = 0.8,
                     label: str = "crate", patrol_to: tuple | None = None) -> dict:
        with self._lock:
            idn = f"user-{self._user_obstacles + 1}"
            if label == "person":
                # People have a fixed human footprint and height regardless of `size`.
                obs = Obstacle(idn, "person", "circle", x, y, r=self.PERSON_RADIUS, height=1.75, dynamic=True)
                if patrol_to is not None:
                    self._validate_walk((x, y), patrol_to)
                    obs.patrol = [(x, y), tuple(patrol_to)]
                    obs.speed = self.PERSON_SPEED
                    obs.patrol_index = 1
            elif patrol_to is not None:
                raise CommandError("invalid_patrol", "Only people can walk a route", 422)
            elif shape == "circle":
                obs = Obstacle(idn, label, "circle", x, y, r=size / 2, height=1.0, dynamic=True)
            else:
                obs = Obstacle(idn, label, "rect", x, y, w=size, h=size, height=1.0, dynamic=True)
            self._check_new_obstacle(obs)
            self.world.obstacles.append(obs)
            self._user_obstacles += 1
            self._grid_dirty = True
            what = "walking person" if obs.moving else ("person" if label == "person" else label)
            walk = f", walking to ({patrol_to[0]:.2f}, {patrol_to[1]:.2f})" if obs.moving else ""
            self._event("warning", "obstacle", f"Obstacle {idn} ({what}) appeared at ({x:.2f}, {y:.2f}){walk}")
            return obs.to_dict()

    def inject_on_route(self) -> dict:
        """Demo helper: drop a barrier across the current route a few metres ahead."""
        with self._lock:
            # Also accepted during a replanning pause (e.g. a person just crossed the route):
            # the pending replan then plans around the new barrier too.
            if self.status not in ("navigating", "replanning") or len(self.path) < 2:
                raise CommandError("no_active_route", "Start a mission first; there is no route to block")
            r = self.world.robot
            pts = [(r.x, r.y)] + self.path[self.waypoint_index :]
            cum = [0.0]
            for a, b in zip(pts, pts[1:]):
                cum.append(cum[-1] + math.dist(a, b))
            remaining = cum[-1]
            for ahead in (3.0, 2.5, 3.5, 4.0, 2.0, 1.6):
                if ahead > remaining - 1.2:
                    continue
                k = next(i for i in range(1, len(cum)) if cum[i] >= ahead)
                (ax, ay), (bx, by) = pts[k - 1], pts[k]
                f = (ahead - cum[k - 1]) / max(cum[k] - cum[k - 1], 1e-9)
                px, py = ax + (bx - ax) * f, ay + (by - ay) * f
                horizontal = abs(bx - ax) >= abs(by - ay)
                w, h = (0.5, 1.8) if horizontal else (1.8, 0.5)
                idn = f"user-{self._user_obstacles + 1}"
                obs = Obstacle(idn, "barrier", "rect", px, py, w=w, h=h, height=1.0, dynamic=True)
                try:
                    self._check_new_obstacle(obs)
                except CommandError:
                    continue
                # Only use a placement that leaves some alternative route, so the
                # demo shows replanning (the Enclosed scenario demonstrates Blocked).
                self.world.obstacles.append(obs)
                self._rebuild_grid()
                trial = plan(self.grid, (r.x, r.y), self.target)
                if not trial.success:
                    self.world.obstacles.pop()
                    self._rebuild_grid()
                    continue
                self._user_obstacles += 1
                self._grid_dirty = True
                if self.status == "replanning":
                    prior = self._replan["obstacle"]
                    self._replan["obstacle"] = f"{prior} and {idn}" if prior else idn
                self._event(
                    "warning",
                    "obstacle",
                    f"Dynamic obstacle {idn} appeared on the route {ahead:.1f} m ahead",
                )
                return obs.to_dict()
            raise CommandError(
                "no_space", "No spot ahead where an obstacle blocks the route but leaves a detour"
            )

    def clear_obstacles(self) -> int:
        with self._lock:
            before = len(self.world.obstacles)
            self.world.obstacles = [o for o in self.world.obstacles if not o.id.startswith("user-")]
            removed = before - len(self.world.obstacles)
            if removed:
                self._grid_dirty = True
                self._event("info", "obstacle", f"Removed {removed} added obstacle(s)")
            return removed

    # Allowed ranges for sensor parameters (validated before they reach the sensors).
    SENSOR_LIMITS = {
        "lidar": {"fov_deg": (30, 360), "resolution_deg": (0.25, 10), "max_range": (1, 30), "noise_std": (0, 0.2)},
        "ultrasonic": {"max_range": (0.2, 5), "cone_deg": (5, 60)},
        "imu": {},
        "odometry": {},
        "safety": {"slow_distance": (0.2, 3), "stop_distance": (0.05, 1.5)},
    }

    def configure_sensor(self, key: str, enabled=None, rate_hz=None, params=None) -> dict:
        params = params or {}
        if key == "camera":
            if params:
                raise CommandError("invalid_params", "The camera accepts only enabled and rate_hz", 422)
            self.configure_perception(enabled=enabled, rate_hz=rate_hz)
            return self.sensor_status()["camera"]
        limits = self.SENSOR_LIMITS[key]
        for name, value in params.items():
            if name not in limits:
                raise CommandError("invalid_params", f"Unknown parameter '{name}' for {key}", 422)
            lo, hi = limits[name]
            if not lo <= value <= hi:
                raise CommandError("invalid_params", f"{key}.{name} must be between {lo} and {hi}", 422)
        with self._lock:
            if key == "safety":
                pol = self.sensors.policy
                slow = params.get("slow_distance", pol.slow_distance)
                stop = params.get("stop_distance", pol.stop_distance)
                if stop >= slow:
                    raise CommandError("invalid_params", "stop_distance must be smaller than slow_distance", 422)
                pol.slow_distance, pol.stop_distance = slow, stop
                self._event("info", "sensor", f"Safety thresholds: slow below {slow:.2f} m, stop below {stop:.2f} m")
                return {"policy": pol.to_dict()}
            status = self.sensors.configure(key, enabled, rate_hz, params)
            changes = [f"{k}={v}" for k, v in {"enabled": enabled, "rate_hz": rate_hz, **params}.items() if v is not None]
            self._event("info", "sensor", f"{status['name']} configured: {', '.join(changes) or 'no change'}")
            return status

    def sensor_status(self) -> dict:
        """All sensors, including the camera and depth channel owned by perception."""
        with self._lock:
            snap = self.sensors.snapshot(self.sim_time)
        p = self.perception.snapshot(self.sim_time)
        cam_health = "disabled" if not p["enabled"] else ("stale" if p["stale"] else ("ok" if p["frame_seq"] else "waiting"))
        camera = {
            "key": "camera", "name": "RGB camera (simulated render)", "kind": "image", "simulated": True,
            "enabled": p["enabled"], "health": cam_health, "rate_hz": p["rate_hz"], "seq": p["frame_seq"],
            "age_s": None, "error": p["last_error"],
            "config": {**p["camera"], "renderer": p["renderer"], "resolution": p["frame_size"]},
            "reading": {"frame": p["frame_seq"], "detections": len(p["detections"]), "processing_ms": p["processing_ms"]},
        }
        depth = {
            "key": "depth", "name": "Depth channel (simulated, from the camera render)", "kind": "depth",
            "simulated": True, "enabled": p["enabled"], "health": cam_health, "rate_hz": p["rate_hz"],
            "seq": p["frame_seq"], "age_s": None, "error": None,
            "config": {"source": "PyBullet depth buffer" if p["renderer"] == "pybullet" else "ray-cast column depth",
                       "range": p["camera"]["range"]},
            "reading": {"nearest_m": (p["scene"].get("nearest") or {}).get("distance")},
        }
        snap["sensors"] = [camera, depth, *snap["sensors"]]
        snap["camera"] = camera
        return snap

    def remove_obstacle(self, obstacle_id: str) -> None:
        with self._lock:
            obs = next((o for o in self.world.obstacles if o.id == obstacle_id), None)
            if obs is None:
                raise CommandError("not_found", f"No obstacle '{obstacle_id}'", 404)
            if not obstacle_id.startswith("user-"):
                raise CommandError("not_movable", "Only obstacles you added can be removed")
            self.world.obstacles.remove(obs)
            self._grid_dirty = True
            self._event("info", "obstacle", f"Obstacle {obstacle_id} removed")

    def select_models(self, **kwargs) -> dict:
        try:
            self.perception.select_models(**kwargs)
        except ValueError as exc:
            raise CommandError("invalid_model", str(exc), 422) from exc
        except RuntimeError as exc:
            raise CommandError("model_unavailable", str(exc), 409) from exc
        snap = self.perception.registry.snapshot()
        pol = snap["policy"]
        with self._lock:
            sec = f", secondary {pol['secondary']}" if pol["secondary"] else ""
            self._event("info", "perception", f"Models: primary {pol['primary']}{sec}, policy {pol['mode']}")
        return snap

    def configure_perception(self, enabled=None, rate_hz=None, confidence=None) -> None:
        self.perception.configure(enabled, rate_hz, confidence)
        with self._lock:
            parts = []
            if enabled is not None:
                parts.append("enabled" if enabled else "disabled")
            if rate_hz is not None:
                parts.append(f"{rate_hz:g} Hz")
            if confidence is not None:
                parts.append(f"confidence threshold {confidence:.2f}")
            if parts:
                self._event("info", "perception", "Perception " + ", ".join(parts))

    def set_detector(self, mode: str) -> None:
        try:
            self.perception.set_mode(mode)
        except ValueError as exc:
            raise CommandError("invalid_mode", str(exc), 422) from exc
        except RuntimeError as exc:
            raise CommandError("detector_unavailable", str(exc), 409) from exc
        with self._lock:
            label = "YOLOv8 inference" if mode == "yolov8" else "simulated (ground-truth) detector"
            self._event("info", "perception", f"Detector switched to {label}")

    # ================================================================ doors and zones
    def _init_doors(self) -> None:
        self.doors = {}
        for o in self.world.obstacles:
            if o.label == "door":
                # Slides along its long side into the wall next to the doorway.
                along_x = o.w >= o.h
                span = max(o.w, o.h)
                opened = (o.x + span, o.y) if along_x else (o.x, o.y + span)
                self.doors[o.id] = {"obs": o, "closed": (o.x, o.y), "open": opened, "last_need": -1e9, "state": "closed"}

    def _update_doors(self) -> None:
        if not self.doors:
            return
        r = self.world.robot
        people = [o for o in self.world.obstacles if o.label == "person"]
        for d in self.doors.values():
            o = d["obs"]
            cx, cy = d["closed"]
            need = math.hypot(r.x - cx, r.y - cy) < DOOR_TRIGGER_ROBOT or any(
                math.hypot(p.x - cx, p.y - cy) < DOOR_TRIGGER_PERSON for p in people
            )
            if need:
                d["last_need"] = self.sim_time
            want_open = need or self.sim_time - d["last_need"] < DOOR_CLOSE_AFTER
            tx, ty = d["open"] if want_open else d["closed"]
            dist = math.hypot(tx - o.x, ty - o.y)
            if dist > 1e-6:
                step = min(DOOR_SPEED * self.dt, dist)
                o.x += (tx - o.x) / dist * step
                o.y += (ty - o.y) / dist * step
                self._grid_dirty = True
                state = "opening" if want_open else "closing"
            else:
                state = "open" if want_open else "closed"
            if state != d["state"] and state in ("open", "closed"):
                self._event("info", "door", f"Door {o.id} {state}")
            d["state"] = state

    def _zone_limit(self, r) -> tuple[float | None, str | None]:
        """Speed limit of any zone the robot is in or about to enter."""
        zones = self.scenario.zones
        if not zones:
            return None, None
        pts = [(r.x, r.y)]
        if len(self.path) > 1:
            wp = self.path[min(self.waypoint_index, len(self.path) - 1)]
            dist = math.hypot(wp[0] - r.x, wp[1] - r.y) or 1.0
            f = min(ZONE_LOOKAHEAD / dist, 1.0)
            pts.append((r.x + (wp[0] - r.x) * f, r.y + (wp[1] - r.y) * f))
        best = None
        for z in zones:
            if any(z.contains(x, y) for x, y in pts) and (best is None or z.max_speed < best.max_speed):
                best = z
        return (best.max_speed, best.name) if best else (None, None)

    # ================================================================ predictive avoidance
    def _predictive_step(self, r) -> tuple[float, bool]:
        """Risk assessment against predicted obstacle motion. Returns (speed factor,
        hold position). With predictive avoidance off the assessment still runs, for
        display and comparison, but does not influence the robot (reactive baseline)."""
        d = self.prediction.decide(r, self.path, self.waypoint_index, self.params["max_speed"], ROBOT_RADIUS,
                                   self.params["safety_margin"], free_segment=self.grid.segment_free)
        if not self.params["predictive"]:
            return 1.0, False
        factor = d["speed_factor"]
        # Slow down immediately; speed up only after the lower speed has been held a while.
        if factor < self._pred_factor:
            self._pred_hold_until = self.sim_time + PRED_SPEEDUP_HOLD
        elif factor > self._pred_factor and self.sim_time < self._pred_hold_until:
            factor = self._pred_factor
        action = d["action"] if factor == d["speed_factor"] else self._pred_action
        if action != self._pred_action:
            if action == "continue":
                self._event("info", "prediction", "Predicted conflict cleared; resuming normal speed")
            else:
                level = "warning" if action in ("wait", "stop") else "info"
                self._event(level, "prediction", d["reason"], risk=d["risk"], ttc=d["ttc"], track=d["track"])
        self._pred_action = action
        self._pred_factor = factor

        if action == "evade":
            if self._evade_target is None:  # keep one evade point until the conflict is over
                self._evade_target = d["evade_to"]
            self._pred_wait_since = None
            return 1.0, False
        if self._evade_target is not None and action == "stop":
            return 1.0, False  # still in conflict: keep heading for (or holding) the evade point
        if self._evade_target is not None:
            # The conflict has passed: plan the route again from where the robot stepped aside.
            self._evade_target = None
            self._plan_cause = "resume"
            self.status = "planning"
            self._event("info", "prediction", "Object passed; replanning from the side position")
            return 1.0, True
        waiting = action in ("wait", "stop")
        if waiting:
            self._pred_wait_since = self._pred_wait_since if self._pred_wait_since is not None else self.sim_time
            waited = self.sim_time - self._pred_wait_since
            if (action == "stop" or waited >= PRED_REPLAN_AFTER) and self.sim_time - self._pred_last_replan >= PRED_REPLAN_COOLDOWN:
                self._pred_last_replan = self.sim_time
                self._replan_around_prediction(d)
        else:
            self._pred_wait_since = None
        return factor, waiting

    def _replan_around_prediction(self, d) -> None:
        """Plan a route that avoids the cells the tracked objects are predicted to sweep."""
        previous = self._route_length()
        old_path, old_plan, old_index = list(self.path), self.last_plan, self.waypoint_index
        self._extra_block = predicted_mask(self.prediction.tracker.tracks, self.grid.rows, self.grid.cols,
                                           self.grid.resolution, self.inflation)
        r = self.world.robot
        rr, rc = self.grid.world_to_cell(r.x, r.y)
        self._extra_block[max(rr - 2, 0): rr + 3, max(rc - 2, 0): rc + 3] = False  # never block the robot itself
        try:
            self._rebuild_grid()
            ok = self._plan("prediction")
        finally:
            self._extra_block = None
            self._grid_dirty = True
        who = f"track {d['track']}" if d["track"] is not None else "a tracked object"
        if ok and (previous is None or self._route_length() <= 1.8 * previous + 2.0):
            self.replans += 1
            self._record_replan("prediction", who, "replanned", previous)
            self._pred_wait_since = None
            self._event("info", "replanned", f"Alternative route selected around the predicted path of {who}: "
                        f"{self.last_plan['length']:.1f} m, validated", obstacle=who)
        else:
            # Keep the current route and keep waiting.
            self.path, self.last_plan, self.waypoint_index = old_path, old_plan, old_index
            self._event("info", "prediction", f"No safe alternative around the predicted path of {who}; waiting")

    # ================================================================ mapping
    def set_planner_map(self, source: str) -> None:
        if source not in PLANNER_MAPS:
            raise CommandError("invalid_map", f"Planner map must be one of {', '.join(PLANNER_MAPS)}", 422)
        with self._lock:
            if source == "imported" and not self.imported_map:
                raise CommandError("no_imported_map", "Import or load a map before planning on it")
            if self.status in ACTIVE:
                raise CommandError("mission_active", "Stop the mission before changing the planner map")
            self.params["planner_map"] = source
            self._grid_dirty = True
            labels = {
                "simulator": "simulator geometry (ground truth)",
                "slam": "the live SLAM map (unknown space traversable, discovered by LiDAR)",
                "imported": f"the imported map '{self.imported_map['name']}'" if self.imported_map else "",
            }
            self._event("info", "mapping", f"Planner now uses {labels[source]}")

    def set_mapping(self, enabled: bool | None = None, clear: bool = False) -> None:
        with self._lock:
            if clear:
                r = self.world.robot
                self.slam.reset((r.x, r.y, r.theta))
                self._grid_dirty = True
                self._event("info", "mapping", "SLAM map cleared; mapping restarts from the current pose")
            if enabled is not None and enabled != self.slam.enabled:
                self.slam.enabled = bool(enabled)
                self._event("info", "mapping", "Mapping resumed" if enabled else "Mapping paused (map frozen)")

    def explore(self) -> None:
        """Autonomous frontier exploration on the SLAM map."""
        with self._lock:
            if self.status in ACTIVE:
                raise CommandError("mission_active", "A mission is already running")
            if self.status == "paused":
                raise CommandError("mission_paused", "Mission is paused; resume or stop it first")
            if not self.sensors.lidar.enabled:
                raise CommandError("no_lidar", "Exploration needs the LiDAR; enable it in the Sensors panel")
            if not self.slam.enabled:
                self.slam.enabled = True
            if self.params["planner_map"] != "slam":
                self.params["planner_map"] = "slam"
                self._grid_dirty = True
                self._event("info", "mapping", "Planner switched to the live SLAM map for exploration")
            self.exploring = True
            self._explore_blacklist = []
            self._explore_coverage = []
            self.explore_goals = 0
            self.mission_id += 1
            self.mission_time = 0.0
            self.distance_travelled = 0.0
            self.replans = 0
            self._event("info", "explore", "Exploration started: driving to frontiers between mapped and unknown space")
            # The first frontier is chosen by the planning step once a scan is in the map.
            self.target = None
            self.path = []
            self.status = "planning"
            self.status_reason = "Waiting for the first LiDAR scan"

    def _frontiers(self) -> list[tuple[float, float, int]]:
        """Frontier clusters on the SLAM map: free cells next to unknown cells.
        Returns (x, y, size) for each cluster's cell nearest its centroid."""
        s = self.slam.map.states()
        free = s == FREE
        unknown = s == UNKNOWN
        near_unknown = np.zeros_like(unknown)
        near_unknown[1:, :] |= unknown[:-1, :]
        near_unknown[:-1, :] |= unknown[1:, :]
        near_unknown[:, 1:] |= unknown[:, :-1]
        near_unknown[:, :-1] |= unknown[:, 1:]
        frontier = free & near_unknown
        labels, n = label_regions(frontier, structure=np.ones((3, 3), dtype=bool))
        res = self.slam.map.resolution
        out = []
        for k in range(1, n + 1):
            rows, cols = np.nonzero(labels == k)
            if len(rows) < MIN_FRONTIER_CELLS:
                continue
            cr, cc = rows.mean(), cols.mean()
            i = int(np.argmin((rows - cr) ** 2 + (cols - cc) ** 2))
            out.append(((cols[i] + 0.5) * res, (rows[i] + 0.5) * res, len(rows)))
        return out

    def _explore_next(self) -> None:
        if self._grid_dirty:
            self._rebuild_grid()
        r = self.world.robot
        if self.explore_goals >= MAX_EXPLORE_GOALS:
            return self._finish_exploration("goal limit reached")
        # Stop when the last few frontiers no longer add map coverage (noise-sized frontiers).
        known = self.slam.map.stats()["known_fraction"]
        self._explore_coverage.append(known)
        if len(self._explore_coverage) > 4 and known - self._explore_coverage[-5] < 0.01:
            return self._finish_exploration("coverage no longer increasing")
        candidates = []
        for fx, fy, size in self._frontiers():
            if math.hypot(fx - r.x, fy - r.y) < 1.0:
                continue
            if any(math.hypot(fx - bx, fy - by) < 1.0 for bx, by in self._explore_blacklist):
                continue
            row, col = self.grid.world_to_cell(fx, fy)
            cell = self.grid.nearest_free(row, col, max_radius=4)
            if cell is None:
                continue
            gx, gy = self.grid.cell_to_world(*cell)
            # Prefer near and large frontiers.
            candidates.append((math.hypot(gx - r.x, gy - r.y) - 0.02 * size, (gx, gy)))
        for _, goal in sorted(candidates)[:6]:
            trial = plan(self.grid, (r.x, r.y), goal)
            if trial.success:
                self.target = (round(goal[0], 3), round(goal[1], 3))
                self.explore_goals += 1
                self._plan_cause = "explore"
                self.status = "planning"
                self.status_reason = ""
                self._event("info", "explore", f"Frontier {self.explore_goals}: heading to ({goal[0]:.1f}, {goal[1]:.1f})")
                return
            self._explore_blacklist.append(goal)
        self._finish_exploration("no reachable frontiers remain")

    def _finish_exploration(self, why: str) -> None:
        self.exploring = False
        stats = self.slam.map.stats()
        self._halt("idle", f"Exploration finished: {why}")
        self.target = None
        self.path = []
        self._event(
            "success",
            "explore",
            f"Exploration finished ({why}): {stats['known_fraction'] * 100:.0f}% of the area mapped, "
            f"pose error {self.slam.pose_error * 100:.0f} cm",
        )

    # --- map files (ROS map_server format) ----------------------------------------------
    def _map_paths(self, name: str) -> tuple[Path, Path]:
        if not MAP_NAME.match(name):
            raise CommandError("invalid_name", "Map names use letters, digits, - and _ (max 40)", 422)
        return self.maps_dir / f"{name}.pgm", self.maps_dir / f"{name}.yaml"

    def export_map(self) -> tuple[bytes, str]:
        with self._lock:
            return self.slam.map.to_pgm(), self.slam.map.to_yaml("map.pgm")

    def save_map(self, name: str) -> dict:
        pgm_path, yaml_path = self._map_paths(name)
        with self._lock:
            if self.slam.map.scans == 0:
                raise CommandError("empty_map", "The SLAM map is empty; let the robot scan first")
            pgm, yaml = self.slam.map.to_pgm(), self.slam.map.to_yaml(pgm_path.name)
            stats = self.slam.map.stats()
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        pgm_path.write_bytes(pgm)
        yaml_path.write_text(yaml, encoding="utf-8")
        with self._lock:
            self._event("info", "mapping", f"Map saved as '{name}' ({stats['known_fraction'] * 100:.0f}% known)")
        return {"name": name, **stats}

    def list_maps(self) -> list[dict]:
        if not self.maps_dir.is_dir():
            return []
        out = []
        for y in sorted(self.maps_dir.glob("*.yaml")):
            if (y.with_suffix(".pgm")).is_file() and MAP_NAME.match(y.stem):
                out.append({"name": y.stem, "modified": datetime.fromtimestamp(y.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
        return out

    def load_map(self, name: str) -> dict:
        pgm_path, yaml_path = self._map_paths(name)
        if not (pgm_path.is_file() and yaml_path.is_file()):
            raise CommandError("not_found", f"No saved map '{name}'", 404)
        return self.import_map(yaml_path.read_text(encoding="utf-8"), pgm_path.read_bytes(), name, source="saved")

    def import_map(self, yaml_text: str, pgm: bytes, name: str, source: str = "imported") -> dict:
        from ..mapping.occupancy import MapFormatError, parse_pgm, parse_yaml, states_from_image

        try:
            meta = parse_yaml(yaml_text)
            img = parse_pgm(pgm)
        except MapFormatError as exc:
            raise CommandError("invalid_map", str(exc), 422) from exc
        states = states_from_image(img, meta)
        m = LogOddsMap.from_states(states, meta["resolution"], (meta["origin"][0], meta["origin"][1]))
        with self._lock:
            self.imported_map = {
                "map": m,
                "name": name,
                "source": source,
                "meta": {
                    "resolution": meta["resolution"],
                    "origin": meta["origin"][:3] if len(meta["origin"]) >= 3 else [*meta["origin"], 0.0],
                    "width_px": int(img.shape[1]),
                    "height_px": int(img.shape[0]),
                    "width_m": round(img.shape[1] * meta["resolution"], 3),
                    "height_m": round(img.shape[0] * meta["resolution"], 3),
                    "negate": meta["negate"],
                    "occupied_thresh": meta["occupied_thresh"],
                    "free_thresh": meta["free_thresh"],
                },
            }
            if self.params["planner_map"] == "imported":
                self._grid_dirty = True
            st = m.stats()
            self._event(
                "info",
                "mapping",
                f"Map '{name}' {'loaded' if source == 'saved' else 'imported'}: {img.shape[1]}x{img.shape[0]} cells at "
                f"{meta['resolution']} m, {st['known_fraction'] * 100:.0f}% known",
            )
            return {"name": name, **self.imported_map["meta"], **st}

    def mapping_status(self) -> dict:
        """Compact mapping/localisation status for every telemetry frame."""
        lidar_ok = self.sensors.lidar.enabled and self.sensors.lidar.reading is not None
        ex, ey, eth = self.slam.estimate
        if not self.slam.enabled:
            state = "paused"
        elif not self.sensors.lidar.enabled:
            state = "no_lidar"
        else:
            state = "mapping"
        return {
            "state": state,
            "source": "simulation",
            "planner_map": self.params["planner_map"],
            "exploring": self.exploring,
            "explore_goals": self.explore_goals,
            "scans": self.slam.map.scans,
            "known_fraction": self.slam.map.stats()["known_fraction"],
            "estimate": {"x": round(ex, 3), "y": round(ey, 3), "heading_deg": round(math.degrees(eth) % 360, 1)},
            "localization": self.slam.localization(lidar_ok),
            # Evaluation only: compares the estimate with the simulator's ground truth.
            "pose_error_m": round(self.slam.pose_error, 3),
            "heading_error_deg": round(self.slam.heading_error_deg, 2),
            "max_pose_error_m": round(self.slam.max_pose_error, 3),
            "odometry_drift_m": (self.sensors.odometry.reading or {}).get("drift_m"),
            "imported": self.imported_map["name"] if self.imported_map else None,
        }

    def mapping_data(self, which: str = "slam") -> dict:
        with self._lock:
            if which == "imported":
                if not self.imported_map:
                    raise CommandError("no_imported_map", "No map has been imported", 404)
                m = self.imported_map["map"]
                extra = {"name": self.imported_map["name"], "meta": self.imported_map["meta"]}
            else:
                m = self.slam.map
                extra = {
                    "trajectory": [list(p) for p in self.slam.trajectory],
                    "truth_trajectory": [list(p) for p in self.slam.truth_trajectory],
                    "scan": [list(p) for p in self.slam.last_scan_points],
                }
            r = self.world.robot
            return {
                "kind": which,
                "frame": "map (= simulator world frame, metres)",
                "resolution": m.resolution,
                "origin": [m.origin[0], m.origin[1], 0.0],
                "rows": m.rows,
                "cols": m.cols,
                "cells": m.to_rows(),
                "legend": {"u": "unknown", "f": "free", "o": "occupied"},
                "stats": m.stats(),
                "status": self.mapping_status(),
                "robot_truth": {"x": round(r.x, 3), "y": round(r.y, 3), "heading_deg": round(math.degrees(r.theta) % 360, 1)},
                "target": {"x": self.target[0], "y": self.target[1]} if self.target else None,
                "path": [[round(x, 3), round(y, 3)] for x, y in self.path],
                "saved_maps": self.list_maps(),
                **extra,
            }

    # ================================================================ readers
    def _status_public(self) -> str:
        return "blocked" if self.status == "blocked_waiting" else self.status

    def snapshot(self) -> dict:
        with self._lock:
            r = self.world.robot
            target = None
            distance = None
            if self.target:
                target = {"x": self.target[0], "y": self.target[1]}
                distance = round(math.hypot(self.target[0] - r.x, self.target[1] - r.y), 3)
            current_wp = None
            if self.path and 0 < self.waypoint_index < len(self.path):
                wx, wy = self.path[self.waypoint_index]
                current_wp = {"index": self.waypoint_index, "x": round(wx, 3), "y": round(wy, 3)}
            remaining = None
            if self.path and self.status in ("navigating", "paused", "planning"):
                pts = [(r.x, r.y)] + self.path[max(self.waypoint_index, 1) :]
                remaining = round(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])), 2)
            travelled = self.distance_travelled
            progress = None
            if self.status == "goal_reached":
                progress = 1.0
            elif remaining is not None and travelled + remaining > 0:
                progress = round(travelled / (travelled + remaining), 3)
            return {
                "type": "telemetry",
                "ts": round(time.time(), 3),  # wall-clock time of this snapshot (epoch seconds)
                "replan_history": list(self.replan_history),
                "version": TELEMETRY_VERSION,
                "seq": self.seq,
                "sim_time": round(self.sim_time, 2),
                "scenario": self.scenario.key,
                "mission": {
                    "id": self.mission_id,
                    "status": self._status_public(),
                    "waiting": self.status == "blocked_waiting",
                    "reason": self.status_reason,
                    "elapsed": round(self.mission_time, 2),
                    "distance_travelled": round(self.distance_travelled, 2),
                    "replans": self.replans,
                    "safety_stops": self.safety_stops,
                    "goal_reached": self.status == "goal_reached",
                    "progress": progress,
                },
                "robot": r.to_dict(),
                "target": target,
                "distance_to_target": distance,
                "path": [[round(x, 3), round(y, 3)] for x, y in self.path],
                "path_version": self.path_version,
                "remaining_path_length": remaining,
                "current_waypoint": current_wp,
                "last_plan": self.last_plan,
                "safety": {
                    "clearance": round(self.clearance, 3),
                    "nearest": self.nearest_obstacle,
                    "warning": self.collision_warning,
                    "collisions": self.collisions,
                    "in_contact": self._in_collision,
                    "inflation": round(self.inflation, 3),
                    "physics": self.physics.backend,
                },
                "obstacles": [o.to_dict() for o in self.world.obstacles],
                "params": dict(self.params),
                "events": list(self.events)[-60:],
                "perception": self.perception.snapshot(self.sim_time),
                "sensors": {**self.sensors.snapshot(self.sim_time), "proximity_stops": self.proximity_stops},
                "mapping": self.mapping_status(),
                "prediction": self.prediction.snapshot(self.params["predictive"]),
                "zone": self.zone,
                "operations": self.operations.snapshot(),
                "doors": [{"id": k, "state": d["state"]} for k, d in self.doors.items()],
            }

    def map_data(self) -> dict:
        with self._lock:
            if self._grid_dirty:
                self._rebuild_grid()
            grid = self.grid.to_dict()
            seen = self.perception.observed_mask()
            if seen.shape == self.grid.blocked.shape:
                grid["cells"] = self.grid.cell_states(seen)
                grid["legend"] = {
                    "#": "occupied",
                    "+": "inflated (unsafe for the robot centre)",
                    ".": "free, observed by the camera",
                    "?": "free, not yet observed (unknown to perception)",
                }
            if self.target:
                grid["target_cell"] = list(self.grid.world_to_cell(*self.target))
            # Cells with a simulated LiDAR return in the last 2 s (sensor-derived observation).
            lidar = self.sensors.lidar_occupied(self.sim_time)
            grid["lidar_occupied"] = ["".join("1" if v else "0" for v in row) for row in lidar]
            return {
                "width": self.world.width,
                "height": self.world.height,
                "scenario": self.scenario.to_dict(),
                "robot_radius": ROBOT_RADIUS,
                "physics": self.physics.backend,
                "obstacles": [o.to_dict() for o in self.world.obstacles],
                "grid": grid,
            }

    def path_data(self) -> dict:
        with self._lock:
            return {
                "status": self._status_public(),
                "path": [[round(x, 3), round(y, 3)] for x, y in self.path],
                "waypoint_index": self.waypoint_index,
                "last_plan": self.last_plan,
            }
