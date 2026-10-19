"""Occupancy grid built from ground-truth obstacle geometry, inflated by the robot
footprint plus a configurable safety margin."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from ..simulation.world import Obstacle


class OccupancyGrid:
    def __init__(self, width: float, height: float, resolution: float = 0.2):
        if resolution <= 0:
            raise ValueError("resolution must be positive")
        self.width = width
        self.height = height
        self.resolution = resolution
        self.cols = int(math.ceil(width / resolution))
        self.rows = int(math.ceil(height / resolution))
        # Cell centres in world coordinates, shape (rows, cols).
        xs = (np.arange(self.cols) + 0.5) * resolution
        ys = (np.arange(self.rows) + 0.5) * resolution
        self._cx, self._cy = np.meshgrid(xs, ys)
        self.occupied = np.zeros((self.rows, self.cols), dtype=bool)  # raw footprint
        self.blocked = np.zeros((self.rows, self.cols), dtype=bool)  # inflated (planning)
        # Soft band just outside the inflated zone: traversable but penalised by A*,
        # so routes keep extra clearance wherever the space allows.
        self.caution = np.zeros((self.rows, self.cols), dtype=bool)

    # --- coordinate conversion -------------------------------------------------
    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """Return (row, col). Points on the far edge are clamped into the grid."""
        col = min(max(int(math.floor(x / self.resolution)), 0), self.cols - 1)
        row = min(max(int(math.floor(y / self.resolution)), 0), self.rows - 1)
        return row, col

    def cell_to_world(self, row: int, col: int) -> tuple[float, float]:
        return ((col + 0.5) * self.resolution, (row + 0.5) * self.resolution)

    def in_grid(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def is_free(self, row: int, col: int) -> bool:
        return self.in_grid(row, col) and not self.blocked[row, col]

    # --- construction -----------------------------------------------------------
    def build(
        self,
        obstacles: Iterable[Obstacle],
        inflation: float,
        moving_extra: float = 0.0,
        caution: float = 0.25,
    ) -> "OccupancyGrid":
        """Rasterise obstacles. ``inflation`` = robot radius + safety margin."""
        occupied = np.zeros_like(self.occupied)
        # Boundary walls: anything closer than `inflation` to the map edge is unsafe.
        edge = np.minimum.reduce(
            [self._cx, self._cy, self.width - self._cx, self.height - self._cy]
        )
        blocked = edge < inflation
        soft = edge < inflation + caution
        for obs in obstacles:
            dist = obs.distance(self._cx, self._cy)
            occupied |= dist <= 0
            extra = moving_extra if obs.moving else 0.0
            blocked |= dist < inflation + extra
            soft |= dist < inflation + extra + caution
        self.occupied = occupied
        self.blocked = blocked
        self.caution = soft & ~blocked
        return self

    def nearest_free(self, row: int, col: int, max_radius: int = 6) -> tuple[int, int] | None:
        if self.is_free(row, col):
            return row, col
        best = None
        best_d = float("inf")
        for dr in range(-max_radius, max_radius + 1):
            for dc in range(-max_radius, max_radius + 1):
                r, c = row + dr, col + dc
                if self.is_free(r, c):
                    d = dr * dr + dc * dc
                    if d < best_d:
                        best, best_d = (r, c), d
        return best

    def segment_free(
        self, x0: float, y0: float, x1: float, y1: float, strict: bool = False
    ) -> bool:
        """True if the straight segment only crosses free (non-inflated) cells.
        With ``strict`` the caution band is treated as blocked too."""
        layer = (self.blocked | self.caution) if strict else self.blocked
        length = math.hypot(x1 - x0, y1 - y0)
        steps = max(int(length / (self.resolution * 0.5)), 1)
        for i in range(steps + 1):
            t = i / steps
            r, c = self.world_to_cell(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            if layer[r, c]:
                return False
        return True

    def cell_states(self, observed: np.ndarray) -> list[str]:
        """Row strings (row 0 = y=0): '#' occupied, '+' inflated, '.' free and
        observed by the camera, '?' free but never observed (unknown)."""
        out = np.full(self.blocked.shape, "?", dtype="<U1")
        out[observed] = "."
        out[self.blocked] = "+"
        out[self.occupied] = "#"
        return ["".join(row) for row in out]

    def to_dict(self) -> dict:
        return {
            "resolution": self.resolution,
            "rows": self.rows,
            "cols": self.cols,
            # Row-major strings ("0"/"1") from row 0 (y=0) upward: compact to send.
            "blocked": ["".join("1" if v else "0" for v in row) for row in self.blocked],
        }
