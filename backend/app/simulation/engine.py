"""Simulation engine and mission state machine.

One engine thread owns the robot: it advances the world at a fixed timestep and is
the only place control commands are produced, so concurrent controllers cannot
fight over the robot. API handlers only mutate state through the locked command
methods below. A second worker thread runs perception (camera + detector).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone

from ..config import Settings
from ..control.controller import PurePursuitController, integrate
from ..navigation.astar import plan
from ..navigation.grid import OccupancyGrid
from ..perception.service import PerceptionService
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
        }
        self.controller = PurePursuitController()
        self.events: deque[dict] = deque(maxlen=200)
        self._event_id = 0
        self.seq = 0
        self.thread_alive = False
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

    def _rebuild_grid(self) -> None:
        self.grid.build(self.world.obstacles, self.inflation, MOVING_EXTRA_INFLATION)
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
                    return self._blocking_obstacle(px, py) or True
            travelled += seg * (1 - t0)
        return None

    def _blocking_obstacle(self, px: float, py: float) -> Obstacle | None:
        """Which obstacle makes the cell at (px, py) unsafe. Cells are blocked by their
        centre, so allow up to one cell diagonal of slack; None means the map edge."""
        reach = self.inflation + self.grid_resolution * 0.75
        best, best_d = None, float("inf")
        for o in self.world.obstacles:
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
            # People yield to the robot: never step into its safety bubble.
            if math.hypot(nx - r.x, ny - r.y) < obs.r + ROBOT_RADIUS + 0.35:
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

    def _step_planning(self) -> None:
        causes = {
            "mission_start": "Planning route with A*",
            "target_changed": "Target changed; planning a new route with A*",
            "resume": "Planning route from the current pose with A*",
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
            self._halt("goal_reached", "")
            self._event(
                "success",
                "goal_reached",
                f"Goal reached in {self.mission_time:.1f} s after {self.distance_travelled:.1f} m "
                f"and {self.replans} replan(s)",
            )
            return

        blocker = self._path_obstruction()
        if blocker is not None and self.sim_time - self.last_replan_time >= REPLAN_COOLDOWN:
            name = blocker.id if isinstance(blocker, Obstacle) else "map edge"
            self._event("warning", "obstruction", f"Route obstructed by {name}; robot stopped, replanning", obstacle=name)
            self._begin_replan("obstruction", name)
            return

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
        speed_factor = min(speed_factor, prox["speed_factor"])

        self.controller.max_speed = self.params["max_speed"]
        cmd = self.controller.compute(
            r, self.path, max(self.waypoint_index - 1, 0), self.dt,
            self.params["max_speed"] * max(speed_factor, 0.05),
        )
        self.waypoint_index = max(self.waypoint_index, cmd.segment_index)
        v, w = cmd.v, cmd.w
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
            self._prox_action = "clear"
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
        for obs in w.obstacles:
            if obs.moving:
                continue
            if float(obs.distance(x, y)) < m:
                raise CommandError(
                    "target_unsafe",
                    f"Target is inside or too close to {obs.id} (needs {m:.2f} m clearance)",
                    409,
                )

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
            self._halt("stopped", "Stopped by operator")
            self._event("info", "mission", "Mission stopped by operator; robot halted")

    def configure(self, max_speed=None, safety_margin=None, moving_obstacles=None) -> None:
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
