"""World model: robot, obstacles and map bounds. All units are metres / radians.

Coordinate frame: origin at the bottom-left corner of the map, +x to the right,
+y up, heading measured counter-clockwise from +x.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

ROBOT_RADIUS = 0.30  # metres, circular footprint


@dataclass
class Obstacle:
    id: str
    label: str  # semantic class used by the camera / simulated detector
    shape: str  # "rect" (axis aligned) or "circle"
    x: float  # centre
    y: float
    w: float = 0.0  # rect width (x extent)
    h: float = 0.0  # rect height (y extent)
    r: float = 0.0  # circle radius
    height: float = 1.0  # physical height, used by the camera renderer
    dynamic: bool = False  # inserted at runtime or moving
    # Optional patrol for moving obstacles: list of (x, y) points, speed in m/s.
    patrol: list[tuple[float, float]] = field(default_factory=list)
    speed: float = 0.0
    patrol_index: int = 0

    @property
    def moving(self) -> bool:
        return bool(self.patrol) and self.speed > 0

    def distance(self, px: np.ndarray | float, py: np.ndarray | float):
        """Signed distance from point(s) to the obstacle surface (negative inside)."""
        if self.shape == "circle":
            return np.hypot(np.asarray(px) - self.x, np.asarray(py) - self.y) - self.r
        dx = np.abs(np.asarray(px) - self.x) - self.w / 2
        dy = np.abs(np.asarray(py) - self.y) - self.h / 2
        outside = np.hypot(np.maximum(dx, 0), np.maximum(dy, 0))
        inside = np.minimum(np.maximum(dx, dy), 0)
        return outside + inside

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "label": self.label,
            "shape": self.shape,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "height": self.height,
            "dynamic": self.dynamic,
            "moving": self.moving,
        }
        if self.shape == "circle":
            data["r"] = self.r
        else:
            data["w"] = self.w
            data["h"] = self.h
        return data

    def copy(self) -> "Obstacle":
        return Obstacle(
            id=self.id,
            label=self.label,
            shape=self.shape,
            x=self.x,
            y=self.y,
            w=self.w,
            h=self.h,
            r=self.r,
            height=self.height,
            dynamic=self.dynamic,
            patrol=list(self.patrol),
            speed=self.speed,
            patrol_index=self.patrol_index,
        )


@dataclass
class RobotState:
    x: float
    y: float
    theta: float
    v: float = 0.0  # linear velocity m/s
    w: float = 0.0  # angular velocity rad/s

    def to_dict(self) -> dict:
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "theta": round(self.theta, 4),
            "heading_deg": round(math.degrees(self.theta) % 360, 1),
            "v": round(self.v, 3),
            "w": round(self.w, 3),
            "radius": ROBOT_RADIUS,
        }


@dataclass
class World:
    width: float
    height: float
    robot: RobotState
    obstacles: list[Obstacle]

    def clearance(self, x: float, y: float) -> tuple[float, Obstacle | None]:
        """Distance from a point to the nearest obstacle surface or map boundary."""
        best = min(x, y, self.width - x, self.height - y)
        nearest: Obstacle | None = None
        for obs in self.obstacles:
            d = float(obs.distance(x, y))
            if d < best:
                best, nearest = d, obs
        return best, nearest

    def in_bounds(self, x: float, y: float) -> bool:
        return 0.0 <= x <= self.width and 0.0 <= y <= self.height

    def inside_obstacle(self, x: float, y: float, margin: float = 0.0) -> Obstacle | None:
        for obs in self.obstacles:
            if float(obs.distance(x, y)) < margin:
                return obs
        return None
