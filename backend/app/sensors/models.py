"""Simulated robot sensors.

Every sensor here is SIMULATED: it measures the simulator's geometry with a
configurable rate, range and (deterministic, seeded) noise model. None of them
reads physical hardware. Readings carry a timestamp (simulation time), a sequence
number and a `simulated: True` flag so the UI can never present them as hardware.

Geometry queries use the same obstacle shapes the planner and PyBullet use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..simulation.world import ROBOT_RADIUS, Obstacle


def cast_rays(ox: float, oy: float, angles: np.ndarray, obstacles: list[Obstacle],
              width: float, height: float, max_range: float):
    """Distance along each ray to the first surface (obstacle or map boundary).
    ``ox``/``oy`` may be scalars or one origin per ray.
    Returns (distances, hit_index) where hit_index -1 = boundary, -2 = no hit in range."""
    dx, dy = np.cos(angles), np.sin(angles)
    n = len(angles)
    # Obstacles that cannot be reached within max_range are skipped (cheap pre-filter).
    cx, cy = float(np.mean(ox)), float(np.mean(oy))
    spread = float(np.max(np.hypot(np.asarray(ox) - cx, np.asarray(oy) - cy))) if np.ndim(ox) else 0.0
    best = np.full(n, np.inf)
    idx = np.full(n, -2, dtype=int)
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(dx > 0, (width - ox) / dx, np.where(dx < 0, -ox / dx, np.inf))
        ty = np.where(dy > 0, (height - oy) / dy, np.where(dy < 0, -oy / dy, np.inf))
        tb = np.minimum(tx, ty)
        m = tb < best
        best[m], idx[m] = tb[m], -1
        for k, o in enumerate(obstacles):
            if float(o.distance(cx, cy)) > max_range + spread:
                continue
            if o.shape == "circle":
                fx, fy = ox - o.x, oy - o.y
                b = fx * dx + fy * dy
                c = fx * fx + fy * fy - o.r * o.r
                disc = b * b - c
                t = np.where(disc >= 0, -b - np.sqrt(np.maximum(disc, 0)), np.inf)
                t = np.where(t > 1e-6, t, np.inf)
            else:
                x0, x1 = o.x - o.w / 2, o.x + o.w / 2
                y0, y1 = o.y - o.h / 2, o.y + o.h / 2
                t1, t2 = (x0 - ox) / dx, (x1 - ox) / dx
                t3, t4 = (y0 - oy) / dy, (y1 - oy) / dy
                tmin = np.maximum(np.minimum(t1, t2), np.minimum(t3, t4))
                tmax = np.minimum(np.maximum(t1, t2), np.maximum(t3, t4))
                tmin[np.isnan(tmin)] = -np.inf
                tmax[np.isnan(tmax)] = -np.inf
                t = np.where((tmax >= tmin) & (tmax > 1e-6), np.maximum(tmin, 1e-6), np.inf)
            m = t < best
            best[m], idx[m] = t[m], k
    idx[best > max_range] = -2
    return best, idx


@dataclass
class SensorBase:
    key: str
    name: str
    kind: str
    rate_hz: float
    enabled: bool = True
    seq: int = 0
    last_time: float | None = None  # simulation time of the latest reading
    error: str | None = None
    reading: dict | None = None
    seed: int = 7
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)

    def reset(self) -> None:
        self.seq = 0
        self.last_time = None
        self.reading = None
        self.error = None
        self._rng = np.random.default_rng(self.seed)

    def due(self, sim_time: float) -> bool:
        return self.enabled and (self.last_time is None or sim_time - self.last_time >= 1.0 / self.rate_hz - 1e-9)

    def config(self) -> dict:
        return {"rate_hz": self.rate_hz}

    def configure(self, params: dict) -> None:
        raise ValueError(f"{self.name} has no configurable parameters besides rate")

    def status(self, sim_time: float) -> dict:
        age = None if self.last_time is None else round(sim_time - self.last_time, 3)
        if not self.enabled:
            health = "disabled"
        elif self.error:
            health = "error"
        elif age is None:
            health = "waiting"
        elif age > 3.0 / self.rate_hz + 0.1:
            health = "stale"
        else:
            health = "ok"
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "simulated": True,
            "enabled": self.enabled,
            "health": health,
            "rate_hz": self.rate_hz,
            "seq": self.seq,
            "age_s": age,
            "error": self.error,
            "config": self.config(),
            "reading": self.reading if self.enabled else None,
        }


@dataclass
class Lidar(SensorBase):
    """2D scanning range finder in the horizontal plane at the sensor height."""

    fov_deg: float = 360.0
    resolution_deg: float = 2.0
    max_range: float = 8.0
    min_range: float = 0.05
    noise_std: float = 0.01  # metres, Gaussian
    mount_height: float = 0.32

    def config(self) -> dict:
        return {
            "rate_hz": self.rate_hz,
            "fov_deg": self.fov_deg,
            "resolution_deg": self.resolution_deg,
            "max_range": self.max_range,
            "noise_std": self.noise_std,
            "mount_height": self.mount_height,
        }

    def configure(self, p: dict) -> None:
        if "fov_deg" in p:
            self.fov_deg = float(p["fov_deg"])
        if "resolution_deg" in p:
            self.resolution_deg = float(p["resolution_deg"])
        if "max_range" in p:
            self.max_range = float(p["max_range"])
        if "noise_std" in p:
            self.noise_std = float(p["noise_std"])

    def measure(self, pose, obstacles, width, height, sim_time) -> np.ndarray:
        x, y, theta = pose
        n = max(int(round(self.fov_deg / self.resolution_deg)), 1)
        rel = np.linspace(-self.fov_deg / 2, self.fov_deg / 2, n, endpoint=self.fov_deg < 360)
        angles = theta + np.radians(rel)
        dist, idx = cast_rays(x, y, angles, obstacles, width, height, self.max_range)
        noisy = dist + self._rng.normal(0.0, self.noise_std, size=dist.shape)
        valid = (idx != -2) & (noisy >= self.min_range)
        ranges = np.where(valid, noisy, np.nan)
        hits = [(float(x + r * math.cos(a)), float(y + r * math.sin(a))) for r, a in zip(ranges, angles) if np.isfinite(r)]
        finite = ranges[np.isfinite(ranges)]
        front = np.abs(np.degrees(np.arctan2(np.sin(angles - theta), np.cos(angles - theta)))) <= 30
        front_vals = ranges[front & np.isfinite(ranges)]
        self.seq += 1
        self.last_time = sim_time
        self.error = None
        self.reading = {
            "frame": self.seq,
            "time": round(sim_time, 3),
            "rays": int(n),
            "valid_returns": int(len(finite)),
            "min_range": round(float(finite.min()), 3) if len(finite) else None,
            "front_min": round(float(front_vals.min()), 3) if len(front_vals) else None,
            # Compact scan for visualisation: [bearing relative to heading (deg), range or null]
            "scan": [[round(float(a), 1), (round(float(r), 3) if np.isfinite(r) else None)] for a, r in zip(rel, ranges)],
        }
        self.hits = hits
        return ranges


@dataclass
class Ultrasonic(SensorBase):
    """Ring of short-range proximity sensors (each a narrow cone sampled by rays)."""

    bearings_deg: tuple = (0.0, 40.0, -40.0, 90.0, -90.0, 180.0)
    cone_deg: float = 30.0
    max_range: float = 2.0
    noise_std: float = 0.01

    def config(self) -> dict:
        return {
            "rate_hz": self.rate_hz,
            "directions_deg": list(self.bearings_deg),
            "cone_deg": self.cone_deg,
            "max_range": self.max_range,
        }

    def configure(self, p: dict) -> None:
        if "max_range" in p:
            self.max_range = float(p["max_range"])
        if "cone_deg" in p:
            self.cone_deg = float(p["cone_deg"])

    def measure(self, pose, obstacles, width, height, sim_time) -> dict:
        x, y, theta = pose
        out = []
        # All channels in one ray cast: 7 rays per cone, each from its sensor on the chassis edge.
        bearings = list(self.bearings_deg)
        offs = np.concatenate([np.radians(np.linspace(b - self.cone_deg / 2, b + self.cone_deg / 2, 7)) for b in bearings])
        base = np.repeat(np.radians(bearings), 7)
        sx = x + ROBOT_RADIUS * np.cos(theta + base)
        sy = y + ROBOT_RADIUS * np.sin(theta + base)
        dist, hit = cast_rays(sx, sy, theta + offs, obstacles, width, height, self.max_range)
        for i, b in enumerate(bearings):
            d, idx = dist[i * 7:(i + 1) * 7], hit[i * 7:(i + 1) * 7]
            d = d[idx != -2]
            if len(d):
                val = float(max(d.min() + self._rng.normal(0, self.noise_std), 0.0))
                out.append({"bearing_deg": b, "range": round(val, 3), "detected": True})
            else:
                out.append({"bearing_deg": b, "range": None, "detected": False})
        self.seq += 1
        self.last_time = sim_time
        self.error = None
        front = [o["range"] for o in out if o["range"] is not None and abs(o["bearing_deg"]) <= 45]
        self.reading = {
            "frame": self.seq,
            "time": round(sim_time, 3),
            "channels": out,
            "front_min": round(min(front), 3) if front else None,
        }
        return self.reading


@dataclass
class Imu(SensorBase):
    """Yaw, yaw rate and longitudinal acceleration with bias + noise (simulated)."""

    gyro_noise: float = 0.01  # rad/s
    gyro_bias: float = 0.002  # rad/s, integrates into yaw drift
    accel_noise: float = 0.05  # m/s^2
    _yaw: float | None = field(default=None, init=False)
    _last_v: float = field(default=0.0, init=False)

    def reset(self) -> None:
        super().reset()
        self._yaw = None
        self._last_v = 0.0

    def config(self) -> dict:
        return {"rate_hz": self.rate_hz, "gyro_noise": self.gyro_noise, "gyro_bias": self.gyro_bias,
                "accel_noise": self.accel_noise}

    def measure(self, robot, dt, sim_time) -> dict:
        if self._yaw is None:
            self._yaw = robot.theta  # initialised once at start-up, then integrated
        rate = robot.w + self.gyro_bias + self._rng.normal(0, self.gyro_noise)
        self._yaw = math.atan2(math.sin(self._yaw + rate * dt), math.cos(self._yaw + rate * dt))
        accel = (robot.v - self._last_v) / max(dt, 1e-6) + self._rng.normal(0, self.accel_noise)
        self._last_v = robot.v
        self.seq += 1
        self.last_time = sim_time
        self.reading = {
            "frame": self.seq,
            "time": round(sim_time, 3),
            "yaw_deg": round(math.degrees(self._yaw) % 360, 2),
            "yaw_rate": round(rate, 4),
            "accel_x": round(accel, 3),
            "yaw_drift_deg": round(math.degrees(math.atan2(math.sin(self._yaw - robot.theta), math.cos(self._yaw - robot.theta))), 3),
        }
        return self.reading


@dataclass
class WheelOdometry(SensorBase):
    """Encoder-based dead reckoning. Wheel slip noise makes the estimate drift from
    ground truth, which is reported as `drift_m` for evaluation."""

    wheel_radius: float = 0.075
    track: float = 0.552
    ticks_per_rev: int = 1024
    slip_std: float = 0.01  # relative per-step slip
    _pose: list | None = field(default=None, init=False)
    _ticks: list = field(default_factory=lambda: [0, 0], init=False)

    def reset(self) -> None:
        super().reset()
        self._pose = None
        self._ticks = [0, 0]

    def config(self) -> dict:
        return {"rate_hz": self.rate_hz, "wheel_radius": self.wheel_radius, "track": self.track,
                "ticks_per_rev": self.ticks_per_rev, "slip_std": self.slip_std}

    def measure(self, robot, dt, sim_time) -> dict:
        if self._pose is None:
            self._pose = [robot.x, robot.y, robot.theta]
        vl = (robot.v - robot.w * self.track / 2) * (1 + self._rng.normal(0, self.slip_std))
        vr = (robot.v + robot.w * self.track / 2) * (1 + self._rng.normal(0, self.slip_std))
        dl, dr = vl * dt, vr * dt
        per_tick = 2 * math.pi * self.wheel_radius / self.ticks_per_rev
        self._ticks[0] += int(round(dl / per_tick))
        self._ticks[1] += int(round(dr / per_tick))
        ds, dth = (dl + dr) / 2, (dr - dl) / self.track
        x, y, th = self._pose
        x += ds * math.cos(th + dth / 2)
        y += ds * math.sin(th + dth / 2)
        th = math.atan2(math.sin(th + dth), math.cos(th + dth))
        self._pose = [x, y, th]
        self.seq += 1
        self.last_time = sim_time
        self.reading = {
            "frame": self.seq,
            "time": round(sim_time, 3),
            "ticks_left": self._ticks[0],
            "ticks_right": self._ticks[1],
            "wheel_speed_left": round(vl / self.wheel_radius, 3),
            "wheel_speed_right": round(vr / self.wheel_radius, 3),
            "estimate": {"x": round(x, 3), "y": round(y, 3), "heading_deg": round(math.degrees(th) % 360, 2)},
            "drift_m": round(math.hypot(x - robot.x, y - robot.y), 3),
        }
        return self.reading
