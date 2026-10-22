"""Multi-object tracker: one constant-velocity Kalman filter per object.

State x = [px, py, vx, vy]. Prediction uses a white-noise-acceleration model
(process noise ``ACCEL_STD``); measurements are LiDAR object centroids with noise
``MEAS_STD``. Measurements are associated greedily, nearest first, inside a gate
that widens with the track's position uncertainty.

Track life cycle:
- tentative: seen fewer than ``CONFIRM_HITS`` times (not used for decisions);
- confirmed: re-observed consistently;
- coasting: not seen in the latest scans (occluded or missed); its state is still
  predicted, with growing uncertainty, and it is reported as uncertain;
- lost: unseen for ``LOST_AFTER`` seconds; removed and reported as an event.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..scene.classes import policy_for

ACCEL_STD = 1.0  # m/s^2: how quickly an object's velocity may change
MEAS_STD = 0.10  # m: centroid measurement noise (LiDAR noise + segment-shape error)
CONFIRM_HITS = 3
COAST_AFTER = 0.25  # s without a measurement: coasting
LOST_AFTER = 1.5  # s without a measurement: track dropped
BASE_GATE = 0.7  # m
MOVING_SPEED = 0.15  # m/s: slower tracks are treated as static


@dataclass
class KTrack:
    id: int
    x: np.ndarray  # state [px, py, vx, vy]
    P: np.ndarray  # covariance 4x4
    born: float
    last_update: float
    last_predict: float
    size: float
    hits: int = 1
    label: str = "obstacle"
    history: list = field(default_factory=list)  # [(t, px, py)] of filtered positions

    @property
    def state(self) -> str:
        if self.hits < CONFIRM_HITS:
            return "tentative"
        if self.last_predict - self.last_update > COAST_AFTER:
            return "coasting"
        return "confirmed"

    @property
    def speed(self) -> float:
        return float(math.hypot(self.x[2], self.x[3]))

    @property
    def pos_std(self) -> float:
        return float(math.sqrt(max(self.P[0, 0] + self.P[1, 1], 0.0) / 2))

    @property
    def vel_std(self) -> float:
        return float(math.sqrt(max(self.P[2, 2] + self.P[3, 3], 0.0) / 2))

    def confidence(self) -> float:
        """0-1 from consistency of observation, recency and velocity uncertainty."""
        hits = min(self.hits / 8.0, 1.0)
        unseen = self.last_predict - self.last_update
        recency = max(0.0, 1.0 - unseen / LOST_AFTER)
        vel = 1.0 / (1.0 + self.vel_std / 0.3)
        return round(hits * recency * vel, 3)


def _F(dt):
    F = np.eye(4)
    F[0, 2] = F[1, 3] = dt
    return F


def _Q(dt):
    q = ACCEL_STD**2
    dt2, dt3, dt4 = dt * dt, dt**3, dt**4
    return q * np.array([
        [dt4 / 4, 0, dt3 / 2, 0],
        [0, dt4 / 4, 0, dt3 / 2],
        [dt3 / 2, 0, dt2, 0],
        [0, dt3 / 2, 0, dt2],
    ])


H = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
R = np.eye(2) * MEAS_STD**2


def predict_state(x, P, dt):
    """Propagate a state and covariance ``dt`` seconds ahead (no measurement)."""
    F = _F(dt)
    return F @ x, F @ P @ F.T + _Q(dt)


class MultiTracker:
    def __init__(self):
        self.tracks: list[KTrack] = []
        self._next = 1
        self.events: list[str] = []  # drained by the engine into its event log
        self.lost_count = 0

    def reset(self) -> None:
        self.tracks.clear()
        self._next = 1
        self.events.clear()
        self.lost_count = 0

    def _predict_all(self, now: float) -> None:
        for t in self.tracks:
            dt = now - t.last_predict
            if dt > 0:
                t.x, t.P = predict_state(t.x, t.P, dt)
                t.last_predict = now

    def update(self, measurements: list[dict], now: float) -> None:
        self._predict_all(now)
        # Greedy association, nearest pairs first, inside an uncertainty-scaled gate.
        pairs = []
        for i, t in enumerate(self.tracks):
            gate = BASE_GATE + 2.0 * t.pos_std
            for j, m in enumerate(measurements):
                d = math.hypot(m["x"] - t.x[0], m["y"] - t.x[1])
                if d <= gate:
                    pairs.append((d, i, j))
        used_t, used_m = set(), set()
        for d, i, j in sorted(pairs):
            if i in used_t or j in used_m:
                continue
            used_t.add(i)
            used_m.add(j)
            t, m = self.tracks[i], measurements[j]
            z = np.array([m["x"], m["y"]])
            S = H @ t.P @ H.T + R
            K = t.P @ H.T @ np.linalg.inv(S)
            t.x = t.x + K @ (z - H @ t.x)
            t.P = (np.eye(4) - K @ H) @ t.P
            t.hits += 1
            t.last_update = now
            t.size = 0.7 * t.size + 0.3 * m["size"]
            t.history.append((now, float(t.x[0]), float(t.x[1])))
            del t.history[:-40]
        for j, m in enumerate(measurements):
            if j in used_m:
                continue
            P0 = np.diag([MEAS_STD**2, MEAS_STD**2, 1.0, 1.0])  # unknown velocity at birth
            self.tracks.append(KTrack(self._next, np.array([m["x"], m["y"], 0.0, 0.0]), P0, now, now, now, m["size"],
                                      history=[(now, m["x"], m["y"])]))
            self._next += 1
        keep = []
        for t in self.tracks:
            unseen = now - t.last_update
            if unseen > LOST_AFTER:
                if t.hits >= CONFIRM_HITS:
                    self.lost_count += 1
                    self.events.append(f"Track {t.id} ({t.label}) lost after {unseen:.1f} s without observations")
                continue
            if t.hits < CONFIRM_HITS and unseen > COAST_AFTER:
                continue  # never-confirmed clutter: drop silently
            keep.append(t)
        self.tracks = keep

    def advance(self, now: float) -> None:
        """Predict all tracks to ``now`` without a measurement (between scans)."""
        self._predict_all(now)

    def label_from(self, camera_tracks: list[dict]) -> None:
        """Attach a semantic class from camera tracks near each LiDAR track.

        A moving track never takes a static class (barrier, shelf, ...): an unrecognised
        moving object passing a wall would otherwise be explained as "barrier".
        """
        for t in self.tracks:
            moving = t.speed >= MOVING_SPEED
            best = None
            for c in camera_tracks:
                if moving and not policy_for(c["label"]).dynamic:
                    continue
                d = math.hypot(c["x"] - t.x[0], c["y"] - t.x[1])
                if d < 0.8 and (best is None or d < best[0]):
                    best = (d, c["label"])
            if best:
                t.label = best[1]
            elif moving and not policy_for(t.label).dynamic:
                t.label = "obstacle"  # drop a static class picked up while it stood still
