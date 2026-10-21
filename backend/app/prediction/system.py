"""Glue between the simulation engine and the predictive pipeline.

LiDAR scan -> object measurements -> Kalman tracks (+ class from camera tracks)
-> per-tick risk assessment and speed decision.

Evaluation metrics use the simulator's ground truth and exist only in simulation:
- prediction error: every confirmed moving track's 1 s-ahead prediction is stored with
  the true obstacle it was matched to at prediction time, and compared with that
  obstacle's true position 1 s later;
- near misses: episodes where the robot's surface comes within NEAR_MISS m of a moving
  obstacle's surface without touching it.
"""

from __future__ import annotations

import math
import time
from collections import deque

from .lidar_objects import PriorMap, extract_objects
from .risk import SHOW_HORIZONS, assess, obstacle_radius, track_rollout
from .tracker import MOVING_SPEED, MultiTracker, predict_state

NEAR_MISS = 0.25  # m surface-to-surface
PRED_ERR_HORIZON = 1.0


class PredictionSystem:
    def __init__(self):
        self.tracker = MultiTracker()
        self.prior: PriorMap | None = None
        self.decision = {"risk": "LOW", "action": "continue", "speed_factor": 1.0, "ttc": None, "track": None,
                         "reason": "No active route", "conflicts": [], "per_track": {}}
        self._last_seq = None
        self.reset_metrics()

    def reset(self, world) -> None:
        # The prior map holds the scenario's fixed structures, as a building map would.
        self.prior = PriorMap(world.width, world.height, [o for o in world.obstacles if not o.dynamic])
        self.tracker.reset()
        self._last_seq = None
        self.reset_metrics()

    def reset_metrics(self) -> None:
        self._pending: deque = deque()
        self.errors: deque = deque(maxlen=500)
        self.near_misses = 0
        self._in_near_miss = set()
        self.min_moving_clearance = None
        self.scan_ms: deque = deque(maxlen=100)
        self.measurements = 0

    # ------------------------------------------------------------ per tick
    def on_tick(self, world, lidar, sim_time: float, camera_tracks) -> None:
        r = world.robot
        reading = lidar.reading if lidar.enabled else None
        if reading is not None and reading["frame"] != self._last_seq and self.prior is not None:
            self._last_seq = reading["frame"]
            started = time.perf_counter()
            meas = extract_objects(
                (r.x, r.y, r.theta),
                [b for b, _ in reading["scan"]],
                [float("nan") if d is None else d for _, d in reading["scan"]],
                self.prior,
            )
            self.measurements = len(meas)
            self.tracker.update(meas, sim_time)
            if camera_tracks is not None:
                cams = camera_tracks() if callable(camera_tracks) else camera_tracks
                if cams:
                    self.tracker.label_from(cams)
            self.scan_ms.append((time.perf_counter() - started) * 1000)
            self._record_predictions(world, sim_time)
        else:
            self.tracker.advance(sim_time)
        self._score_predictions(world, sim_time)
        self._near_misses(world)

    def decide(self, robot, path, wp_index, nominal_speed, robot_radius, margin) -> dict:
        self.decision = assess((robot.x, robot.y, robot.theta), path, wp_index, nominal_speed,
                               self.tracker.tracks, robot_radius, margin)
        return self.decision

    def idle(self, reason: str = "No active route") -> None:
        self.decision = {**self.decision, "risk": "LOW", "action": "continue", "speed_factor": 1.0, "ttc": None,
                         "track": None, "reason": reason, "conflicts": []}

    # ------------------------------------------------------------ evaluation
    def _record_predictions(self, world, now: float) -> None:
        movers = [o for o in world.obstacles if o.moving]
        for t in self.tracker.tracks:
            if t.state != "confirmed" or t.speed < MOVING_SPEED or not movers:
                continue
            gt = min(movers, key=lambda o: math.hypot(o.x - t.x[0], o.y - t.x[1]))
            if math.hypot(gt.x - t.x[0], gt.y - t.x[1]) > 0.8:
                continue
            x, _ = predict_state(t.x, t.P, PRED_ERR_HORIZON)
            self._pending.append((now + PRED_ERR_HORIZON, gt.id, float(x[0]), float(x[1])))

    def _score_predictions(self, world, now: float) -> None:
        by_id = {o.id: o for o in world.obstacles}
        while self._pending and self._pending[0][0] <= now:
            _, oid, px, py = self._pending.popleft()
            o = by_id.get(oid)
            if o is not None:
                self.errors.append(math.hypot(o.x - px, o.y - py))

    def _near_misses(self, world) -> None:
        r = world.robot
        from ..simulation.world import ROBOT_RADIUS

        for o in world.obstacles:
            if not o.moving:
                continue
            gap = float(o.distance(r.x, r.y)) - ROBOT_RADIUS
            self.min_moving_clearance = gap if self.min_moving_clearance is None else min(self.min_moving_clearance, gap)
            if 0 < gap < NEAR_MISS:
                if o.id not in self._in_near_miss:
                    self._in_near_miss.add(o.id)
                    self.near_misses += 1
            elif gap >= NEAR_MISS + 0.1:
                self._in_near_miss.discard(o.id)

    def metrics(self) -> dict:
        errs = list(self.errors)
        lat = list(self.scan_ms)
        return {
            "prediction_error_1s_mean": round(sum(errs) / len(errs), 3) if errs else None,
            "prediction_error_1s_max": round(max(errs), 3) if errs else None,
            "prediction_samples": len(errs),
            "near_misses": self.near_misses,
            "min_moving_clearance": round(self.min_moving_clearance, 3) if self.min_moving_clearance is not None else None,
            "tracks_lost": self.tracker.lost_count,
            "tracking_ms_mean": round(sum(lat) / len(lat), 2) if lat else None,
            "tracking_ms_max": round(max(lat), 2) if lat else None,
        }

    # ------------------------------------------------------------ telemetry
    def snapshot(self, enabled: bool) -> dict:
        tracks = []
        per = self.decision.get("per_track", {})
        for t in self.tracker.tracks:
            if t.state == "tentative":
                continue
            moving = t.speed >= MOVING_SPEED
            pos, sig = track_rollout(t, SHOW_HORIZONS)
            preds = [{"t": h, "x": round(float(p[0]), 2), "y": round(float(p[1]), 2), "sigma": round(float(sg), 2)}
                     for h, p, sg in zip(SHOW_HORIZONS, pos, sig)]
            info = per.get(t.id, {})
            tracks.append({
                "id": t.id,
                "label": t.label,
                "state": t.state,
                "x": round(float(t.x[0]), 2),
                "y": round(float(t.x[1]), 2),
                "vx": round(float(t.x[2]), 2),
                "vy": round(float(t.x[3]), 2),
                "speed": round(t.speed, 2),
                "heading_deg": round(math.degrees(math.atan2(t.x[3], t.x[2])) % 360, 0) if moving else None,
                "moving": moving,
                "radius": round(obstacle_radius(t), 2),
                "confidence": t.confidence(),
                "pos_std": round(t.pos_std, 2),
                "predicted": preds,
                "risk": info.get("risk", "LOW"),
                "ttc": info.get("ttc"),
            })
        d = self.decision
        return {
            "enabled": enabled,
            "source": "simulated LiDAR (background-subtracted against the prior map) + Kalman tracking",
            "risk": d["risk"],
            "action": d["action"] if enabled else "monitor_only",
            "speed_factor": d["speed_factor"] if enabled else 1.0,
            "ttc": d["ttc"],
            "track": d["track"],
            "reason": d["reason"] if enabled else f"Predictive avoidance off (reactive baseline). {d['reason']}",
            "conflicts": d["conflicts"],
            "tracks": tracks,
            "measurements": self.measurements,
            "metrics": self.metrics(),
        }
