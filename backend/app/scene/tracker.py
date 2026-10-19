"""Camera-derived obstacle tracks.

Each ranged detection is projected into the world frame using the robot pose at
capture time, then associated with an existing track of the same class (nearest
within a gate) or starts a new one. Tracks that are not re-observed become
"stale" and are dropped after a timeout, so missing or noisy detections never
leave permanent phantom obstacles.

These tracks are for perception visualisation and evaluation. Collision
avoidance in the simulator uses ground-truth geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .classes import policy_for

ASSOCIATION_GATE = 0.9  # metres
STALE_AFTER = 1.0  # seconds without an observation
DROP_AFTER = 3.0
SMOOTHING = 0.5  # exponential moving average weight for new observations
MIN_HITS_CONFIRMED = 2


@dataclass
class Track:
    id: int
    label: str
    x: float
    y: float
    first_seen: float
    last_seen: float
    hits: int = 1
    vx: float = 0.0
    vy: float = 0.0
    sources: set = field(default_factory=set)

    def to_dict(self, now: float) -> dict:
        age = now - self.last_seen
        return {
            "id": self.id,
            "label": self.label,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "speed": round(math.hypot(self.vx, self.vy), 2),
            "hits": self.hits,
            "confirmed": self.hits >= MIN_HITS_CONFIRMED,
            "stale": age > STALE_AFTER,
            "age": round(age, 2),
            "dynamic": policy_for(self.label).dynamic,
            "source": "/".join(sorted(self.sources)),
        }


class ObstacleTracker:
    def __init__(self):
        self.tracks: list[Track] = []
        self._next_id = 1
        self.rejected = 0  # detections dropped (no range, ignored class, bad values)

    def reset(self) -> None:
        self.tracks.clear()
        self.rejected = 0

    def update(self, detections: list[dict], pose: tuple[float, float, float], now: float) -> None:
        x0, y0, theta = pose
        used: set[int] = set()
        for d in detections:
            dist = d.get("distance")
            bearing = d.get("bearing_deg")
            if (
                not policy_for(d["label"]).obstacle
                or dist is None
                or bearing is None
                or not math.isfinite(dist)
                or dist <= 0
            ):
                self.rejected += 1
                continue
            ang = theta + math.radians(bearing)
            # Detections range to the visible surface; push to the assumed centre.
            r = dist + policy_for(d["label"]).footprint
            px, py = x0 + r * math.cos(ang), y0 + r * math.sin(ang)

            best, best_d = None, ASSOCIATION_GATE
            for t in self.tracks:
                if t.id in used or t.label != d["label"]:
                    continue
                gap = math.hypot(t.x - px, t.y - py)
                if gap < best_d:
                    best, best_d = t, gap
            if best is None:
                best = Track(self._next_id, d["label"], px, py, now, now)
                self._next_id += 1
                self.tracks.append(best)
            else:
                dt = max(now - best.last_seen, 1e-3)
                nx = best.x + SMOOTHING * (px - best.x)
                ny = best.y + SMOOTHING * (py - best.y)
                best.vx, best.vy = (nx - best.x) / dt, (ny - best.y) / dt
                best.x, best.y = nx, ny
                best.last_seen = now
                best.hits += 1
            best.sources.add(d.get("source", "unknown"))
            used.add(best.id)
        self.tracks = [t for t in self.tracks if now - t.last_seen <= DROP_AFTER]

    def snapshot(self, now: float) -> list[dict]:
        return [t.to_dict(now) for t in self.tracks]
