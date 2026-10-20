"""Sensor suite: schedules the simulated sensors, keeps their health, and turns
range measurements into a proximity safety decision for the controller.

Decision sources are reported explicitly so the UI can show which sensor caused a
slow-down or stop. The ground-truth collision layer in the engine stays active
regardless; these sensors add a measurement-driven layer on top of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..simulation.world import ROBOT_RADIUS
from .models import Imu, Lidar, Ultrasonic, WheelOdometry

LIDAR_MEMORY_S = 2.0  # how long a LiDAR return keeps a grid cell marked as observed-occupied


@dataclass
class ProximityPolicy:
    slow_distance: float = 0.9  # surface clearance (m) below which speed is reduced
    stop_distance: float = 0.3  # surface clearance (m) below which the robot stops
    slow_factor_min: float = 0.3  # speed factor reached at the stop distance
    degraded_factor: float = 0.3  # speed factor when no proximity sensor is fresh

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class SensorSuite:
    def __init__(self, grid_shape: tuple[int, int], resolution: float):
        self.lidar = Lidar("lidar", "2D LiDAR (simulated)", "range_scan", rate_hz=10.0, seed=11)
        self.ultrasonic = Ultrasonic("ultrasonic", "Ultrasonic ring (simulated)", "proximity", rate_hz=10.0, seed=12)
        self.imu = Imu("imu", "IMU (simulated)", "inertial", rate_hz=20.0, seed=13)
        self.odometry = WheelOdometry("odometry", "Wheel odometry (simulated)", "odometry", rate_hz=20.0, seed=14)
        self.sensors = {s.key: s for s in (self.lidar, self.ultrasonic, self.imu, self.odometry)}
        self.policy = ProximityPolicy()
        self.resolution = resolution
        self.lidar_seen = np.full(grid_shape, -1e9)  # sim time of the latest LiDAR hit per cell
        self.decision = {"action": "clear", "speed_factor": 1.0, "front_clearance": None, "sources": []}
        self._sim_time = 0.0

    def reset(self) -> None:
        for s in self.sensors.values():
            s.reset()
        self.lidar_seen[:] = -1e9
        self.decision = {"action": "clear", "speed_factor": 1.0, "front_clearance": None, "sources": []}

    # ------------------------------------------------------------ configuration
    def configure(self, key: str, enabled=None, rate_hz=None, params=None) -> dict:
        if key not in self.sensors:
            raise KeyError(key)
        s = self.sensors[key]
        if rate_hz is not None:
            s.rate_hz = float(rate_hz)
        if params:
            s.configure(params)
        if enabled is not None:
            s.enabled = bool(enabled)
            if not s.enabled:
                s.reading = None
        return s.status(self._sim_time)

    # ------------------------------------------------------------ sampling
    def step(self, world, dt: float, sim_time: float) -> None:
        self._sim_time = sim_time
        r = world.robot
        pose = (r.x, r.y, r.theta)
        if self.lidar.due(sim_time):
            try:
                self.lidar.measure(pose, world.obstacles, world.width, world.height, sim_time)
                self._mark_lidar(self.lidar.hits, sim_time)
            except Exception as exc:  # a sensor fault must not stop the simulation
                self.lidar.error = f"{type(exc).__name__}"
        if self.ultrasonic.due(sim_time):
            try:
                self.ultrasonic.measure(pose, world.obstacles, world.width, world.height, sim_time)
            except Exception as exc:
                self.ultrasonic.error = f"{type(exc).__name__}"
        # IMU and odometry integrate every tick (they need continuous motion data);
        # their published reading is refreshed at the configured rate.
        for s in (self.imu, self.odometry):
            if s.enabled:
                s.measure(r, dt, sim_time)

    def _mark_lidar(self, hits, sim_time: float) -> None:
        rows, cols = self.lidar_seen.shape
        for x, y in hits:
            c = min(max(int(x / self.resolution), 0), cols - 1)
            rr = min(max(int(y / self.resolution), 0), rows - 1)
            self.lidar_seen[rr, c] = sim_time

    def lidar_occupied(self, sim_time: float) -> np.ndarray:
        return (sim_time - self.lidar_seen) <= LIDAR_MEMORY_S

    # ------------------------------------------------------------ safety decision
    def _fresh(self, s) -> bool:
        return s.status(self._sim_time)["health"] == "ok" and s.reading is not None

    def proximity(self, robot, corridor_length: float) -> dict:
        """Measured clearance in the robot's driving corridor (robot width, up to the
        next waypoint) and the resulting speed decision."""
        sources = []
        clearances = []
        if self._fresh(self.lidar):
            sources.append("lidar")
            scan = self.lidar.reading["scan"]
            for bearing, rng in scan:
                if rng is None:
                    continue
                a = math.radians(bearing)
                fx, lat = rng * math.cos(a), rng * math.sin(a)  # robot frame
                if fx > 0 and abs(lat) <= ROBOT_RADIUS + 0.05 and fx <= corridor_length + ROBOT_RADIUS:
                    clearances.append(fx - ROBOT_RADIUS)
        if self._fresh(self.ultrasonic):
            sources.append("ultrasonic")
            ch = next((c for c in self.ultrasonic.reading["channels"] if c["bearing_deg"] == 0.0), None)
            # The forward channel is a cone: only trust it for close-range stops.
            if ch and ch["range"] is not None and ch["range"] <= self.policy.stop_distance:
                clearances.append(ch["range"])
        p = self.policy
        if not sources:
            decision = {"action": "degraded", "speed_factor": p.degraded_factor, "front_clearance": None, "sources": []}
        else:
            front = min(clearances) if clearances else None
            if front is None or front >= p.slow_distance:
                action, factor = "clear", 1.0
            elif front <= p.stop_distance:
                action, factor = "stop", 0.0
            else:
                span = p.slow_distance - p.stop_distance
                factor = p.slow_factor_min + (1 - p.slow_factor_min) * (front - p.stop_distance) / span
                action = "slow"
            decision = {
                "action": action,
                "speed_factor": round(factor, 3),
                "front_clearance": round(front, 3) if front is not None else None,
                "sources": sources,
            }
        self.decision = decision
        return decision

    # ------------------------------------------------------------ readers
    def snapshot(self, sim_time: float) -> dict:
        return {
            "sensors": [s.status(sim_time) for s in self.sensors.values()],
            "proximity": dict(self.decision),
            "policy": self.policy.to_dict(),
        }
