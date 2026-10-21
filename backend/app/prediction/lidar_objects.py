"""Turn a LiDAR scan into object measurements.

1. Background subtraction: returns that lie on the *prior map of fixed structures*
   (walls, racking, pallets known when the scenario was loaded, like a building map a
   real robot would carry) are removed. What remains comes from things that are not in
   that map: people, carts, boxes placed later.
2. Segmentation: consecutive returns (in scan order) closer than a gap threshold form
   one segment, the standard way to split a 2D scan into objects.
3. Each segment gives one measurement: its centroid, pushed away from the sensor by
   half the segment's width (a LiDAR only sees the near side of an object, so the raw
   centroid is biased towards the robot), and a size estimate.

The measurement is in world coordinates because the scan is taken at the robot's pose.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt

BACKGROUND_TOLERANCE = 0.15  # m: returns this close to a mapped structure are background
SEGMENT_GAP = 0.35  # m: larger jumps between consecutive returns start a new segment
MIN_POINTS = 2
MAX_OBJECT_SIZE = 2.5  # m: longer segments are walls/structure we failed to subtract
FIELD_RES = 0.05


class PriorMap:
    """Distance field to the fixed structures (and the map boundary)."""

    def __init__(self, width: float, height: float, obstacles):
        self.width, self.height = width, height
        cols, rows = int(math.ceil(width / FIELD_RES)), int(math.ceil(height / FIELD_RES))
        xs = (np.arange(cols) + 0.5) * FIELD_RES
        ys = (np.arange(rows) + 0.5) * FIELD_RES
        cx, cy = np.meshgrid(xs, ys)
        solid = np.zeros((rows, cols), dtype=bool)
        for o in obstacles:
            solid |= o.distance(cx, cy) <= 0
        self.field = distance_transform_edt(~solid) * FIELD_RES if solid.any() else np.full(solid.shape, np.inf)
        self.rows, self.cols = rows, cols

    def distance(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Distance to the nearest fixed structure or map edge."""
        c = np.clip((x / FIELD_RES).astype(int), 0, self.cols - 1)
        r = np.clip((y / FIELD_RES).astype(int), 0, self.rows - 1)
        edge = np.minimum.reduce([x, y, self.width - x, self.height - y])
        return np.minimum(self.field[r, c], edge)


def extract_objects(pose, rel_deg, ranges, prior: PriorMap) -> list[dict]:
    """Object measurements from one scan. ``rel_deg`` are bearings relative to the
    robot heading, ``ranges`` NaN where nothing was hit."""
    x0, y0, th = pose
    rel = np.radians(np.asarray(rel_deg, dtype=float))
    rng = np.asarray(ranges, dtype=float)
    hit = np.isfinite(rng)
    a = th + rel
    px = x0 + np.where(hit, rng, 0) * np.cos(a)
    py = y0 + np.where(hit, rng, 0) * np.sin(a)
    fg = hit.copy()
    fg[hit] = prior.distance(px[hit], py[hit]) > BACKGROUND_TOLERANCE

    # Segment foreground returns in scan order (wrapping around for a 360 deg scan).
    idx = np.nonzero(fg)[0]
    if len(idx) == 0:
        return []
    segments: list[list[int]] = [[idx[0]]]
    for i in idx[1:]:
        j = segments[-1][-1]
        if i - j <= 2 and math.hypot(px[i] - px[j], py[i] - py[j]) <= SEGMENT_GAP:
            segments[-1].append(i)
        else:
            segments.append([i])
    if len(segments) > 1:
        first, last = segments[0], segments[-1]
        n = len(rng)
        if (first[0] + n - last[-1]) <= 2 and math.hypot(px[first[0]] - px[last[-1]], py[first[0]] - py[last[-1]]) <= SEGMENT_GAP:
            segments[0] = last + first
            segments.pop()

    out = []
    for seg in segments:
        if len(seg) < MIN_POINTS:
            continue
        sx, sy = px[seg], py[seg]
        width = float(math.hypot(sx[-1] - sx[0], sy[-1] - sy[0]))
        if width > MAX_OBJECT_SIZE:
            continue
        cx, cy = float(sx.mean()), float(sy.mean())
        # Push the centroid away from the sensor by half the visible width.
        d = math.hypot(cx - x0, cy - y0) or 1.0
        shift = width / 2
        out.append({
            "x": cx + (cx - x0) / d * shift,
            "y": cy + (cy - y0) / d * shift,
            "size": max(width, 0.2),
            "points": len(seg),
            "range": round(d, 2),
        })
    return out
