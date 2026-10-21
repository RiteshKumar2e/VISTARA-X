import math

import numpy as np
import pytest

from app.prediction.lidar_objects import PriorMap, extract_objects
from app.prediction.risk import assess, robot_rollout
from app.prediction.tracker import CONFIRM_HITS, LOST_AFTER, MultiTracker
from app.simulation.world import Obstacle
from conftest import run_until


def _feed(tracker, points, t0=0.0, dt=0.1):
    for i, (x, y) in enumerate(points):
        tracker.update([{"x": x, "y": y, "size": 0.6}], t0 + i * dt)


def test_kalman_estimates_velocity_from_noisy_positions():
    rng = np.random.default_rng(1)
    tr = MultiTracker()
    pts = [(2 + 0.8 * 0.1 * i + rng.normal(0, 0.05), 5 - 0.4 * 0.1 * i + rng.normal(0, 0.05)) for i in range(40)]
    _feed(tr, pts)
    (t,) = tr.tracks
    assert t.state == "confirmed"
    assert abs(t.x[2] - 0.8) < 0.15 and abs(t.x[3] + 0.4) < 0.15
    assert t.confidence() > 0.5


def test_track_lifecycle_tentative_confirmed_coasting_lost():
    tr = MultiTracker()
    _feed(tr, [(5.0, 5.0)] * (CONFIRM_HITS - 1))
    assert tr.tracks[0].state == "tentative"
    _feed(tr, [(5.0, 5.0)] * 3, t0=0.2)
    t = tr.tracks[0]
    assert t.state == "confirmed"
    tr.update([], 0.9)  # no measurement
    assert t.state == "coasting" and t.confidence() < 1
    tr.update([], 0.5 + LOST_AFTER + 0.1)
    assert tr.tracks == [] and tr.lost_count == 1
    assert "lost" in tr.events[-1]


def test_two_objects_keep_their_ids():
    tr = MultiTracker()
    for i in range(10):
        t = i * 0.1
        tr.update([{"x": 2 + 0.5 * t, "y": 2, "size": 0.5}, {"x": 8 - 0.5 * t, "y": 8, "size": 0.5}], t)
    ids = {round(tk.x[1]): tk.id for tk in tr.tracks}
    assert len(tr.tracks) == 2 and ids[2] != ids[8]


def test_lidar_background_subtraction_and_centroid():
    wall = Obstacle("wall", "barrier", "rect", 10.0, 9.0, w=20.0, h=0.3)
    prior = PriorMap(20, 12, [wall])
    person = (6.0, 6.0, 0.3)
    pose = (2.0, 6.0, 0.0)
    rel = np.arange(-180, 180, 1.0)
    ranges = []
    for b in rel:
        a = math.radians(b)
        dx, dy = math.cos(a), math.sin(a)
        best = math.inf
        # person circle
        fx, fy = pose[0] - person[0], pose[1] - person[1]
        bq = 2 * (fx * dx + fy * dy)
        c = fx * fx + fy * fy - person[2] ** 2
        disc = bq * bq - 4 * c
        if disc >= 0:
            tt = (-bq - math.sqrt(disc)) / 2
            if tt > 0:
                best = tt
        # wall face at y = 8.85
        if dy > 1e-6:
            best = min(best, (8.85 - pose[1]) / dy)
        ranges.append(best if best <= 8.0 else math.nan)
    objs = extract_objects(pose, rel, ranges, prior)
    assert len(objs) == 1  # the wall is background
    assert math.hypot(objs[0]["x"] - 6.0, objs[0]["y"] - 6.0) < 0.2


class _T:
    """Minimal stand-in for a confirmed track."""

    def __init__(self, x, y, vx, vy, state="confirmed", conf=0.9, size=0.6, id=1):
        self.id, self.label, self.size = id, "person", size
        self.x = np.array([x, y, vx, vy])
        self.P = np.diag([0.01, 0.01, 0.01, 0.01])
        self.state = state
        self._conf = conf

    @property
    def speed(self):
        return math.hypot(self.x[2], self.x[3])

    def confidence(self):
        return self._conf


PATH = [(1.0, 6.0), (19.0, 6.0)]


def test_crossing_obstacle_is_high_risk_and_robot_yields():
    # Person 2 m to the side of the route, 2.5 m ahead, walking straight onto it.
    t = _T(3.5, 8.0, 0.0, -1.0)
    d = assess((1.0, 6.0, 0.0), PATH, 1, 1.0, [t], 0.3, 0.15)
    assert d["risk"] in ("HIGH", "MEDIUM") and d["ttc"] is not None
    assert d["action"] in ("slow", "crawl", "wait") and d["speed_factor"] < 1.0
    assert d["conflicts"] and d["conflicts"][0]["track"] == 1
    assert "Predicted path conflict" in d["reason"]


def test_obstacle_walking_away_is_low_risk():
    t = _T(3.0, 8.0, 0.0, 1.0)
    d = assess((1.0, 6.0, 0.0), PATH, 1, 1.0, [t], 0.3, 0.15)
    assert d["risk"] == "LOW" and d["action"] == "continue" and d["ttc"] is None


def test_uncertain_track_limits_speed_without_ttc():
    t = _T(2.5, 6.6, 0.0, 0.0, state="coasting", conf=0.2)
    d = assess((1.0, 6.0, 0.0), PATH, 1, 1.0, [t], 0.3, 0.15)
    assert d["risk"] == "MEDIUM" and d["ttc"] is None
    assert d["speed_factor"] <= 0.5 and "Uncertain track" in d["reason"]


def test_robot_rollout_follows_the_route():
    pts = robot_rollout((0.0, 0.0, 0.0), [(0, 0), (2, 0), (2, 2)], 1, 1.0, [1.0, 3.0, 10.0])
    assert np.allclose(pts, [[1, 0], [2, 1], [2, 2]])


@pytest.fixture
def crossing(engine):
    engine.reset("crossing")
    return engine


def test_predictive_mission_in_crossing_scenario(crossing):
    e = crossing
    e.set_target(18.5, 6.0)
    e.navigate()
    assert run_until(e, {"goal_reached"}, max_seconds=90)
    assert e.collisions == 0
    assert any(ev["type"] == "prediction" for ev in e.events)
    snap = e.snapshot()["prediction"]
    assert snap["enabled"] and snap["metrics"]["prediction_samples"] > 0
    assert snap["metrics"]["prediction_error_1s_mean"] < 0.5


def test_reactive_baseline_reports_but_does_not_act(crossing):
    e = crossing
    e.configure(predictive=False)
    e.set_target(18.5, 6.0)
    e.navigate()
    for _ in range(int(12 / e.dt)):
        e.step()
    snap = e.snapshot()["prediction"]
    assert snap["enabled"] is False and snap["action"] == "monitor_only"
    assert not any(ev["type"] == "prediction" for ev in e.events)
    tracks = snap["tracks"]
    assert tracks and all(len(t["predicted"]) == 4 for t in tracks)
