"""Explored-area mask: which occupancy-grid cells the camera has actually seen.

Cells never covered by a camera ray are reported as UNKNOWN in GET /map. This is
the perception view of the map; the planner still uses ground-truth geometry.
"""

from __future__ import annotations

import numpy as np


class ObservationMask:
    def __init__(self, rows: int, cols: int, resolution: float):
        self.rows, self.cols, self.resolution = rows, cols, resolution
        self.seen = np.zeros((rows, cols), dtype=bool)

    def reset(self) -> None:
        self.seen[:] = False

    def mark_rays(self, origin: tuple[float, float], angles: np.ndarray, ranges: np.ndarray) -> None:
        """Mark cells along each ray up to (and including) its hit distance."""
        ox, oy = origin
        step = self.resolution * 0.5
        max_r = float(ranges.max()) if len(ranges) else 0.0
        ts = np.arange(0.0, max_r + step, step)
        # (rays, samples) grid of sample points, masked beyond each ray's range.
        xs = ox + np.cos(angles)[:, None] * ts[None, :]
        ys = oy + np.sin(angles)[:, None] * ts[None, :]
        valid = ts[None, :] <= (ranges[:, None] + step)
        cols = np.clip((xs / self.resolution).astype(int), 0, self.cols - 1)[valid]
        rows = np.clip((ys / self.resolution).astype(int), 0, self.rows - 1)[valid]
        self.seen[rows, cols] = True

    def coverage(self) -> float:
        return float(self.seen.mean())
