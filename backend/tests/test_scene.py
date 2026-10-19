import math

import numpy as np

from app.navigation.grid import OccupancyGrid
from app.scene.classes import policy_for
from app.scene.observation import ObservationMask
from app.scene.tracker import DROP_AFTER, STALE_AFTER, ObstacleTracker
from app.scene.understanding import summarise
from app.simulation.world import Obstacle


def det(label, distance, bearing=0.0, source="ground_truth"):
    return {"label": label, "distance": distance, "bearing_deg": bearing, "source": source}


def test_class_policy_mapping():
    assert policy_for("person").obstacle and policy_for("person").dynamic
    assert policy_for("shelf").obstacle and not policy_for("shelf").dynamic
    assert not policy_for("tv").obstacle  # COCO classes default to ignore
    assert not policy_for("something-new").obstacle


def test_summary_ignores_irrelevant_classes():
    s = summarise([det("tv", 1.0), det("shelf", 3.0)])
    assert s["relevant_count"] == 1 and s["ignored_count"] == 1
    assert s["nearest"]["label"] == "shelf"
    assert s["speed_factor"] == 1.0
    assert summarise([det("person", 1.5, 5.0)])["speed_factor"] == 0.5
    assert summarise([det("person", 1.5, 60.0)])["speed_factor"] == 1.0  # not ahead


def test_tracker_projects_into_world_and_associates():
    tr = ObstacleTracker()
    # Robot at (2, 3) facing +x; person 2 m ahead.
    tr.update([det("person", 2.0)], (2.0, 3.0, 0.0), now=0.0)
    assert len(tr.tracks) == 1
    t = tr.tracks[0]
    assert math.isclose(t.y, 3.0, abs_tol=1e-6) and 4.0 < t.x < 4.6
    # Same object observed again slightly moved: associated, not duplicated.
    tr.update([det("person", 2.1)], (2.0, 3.0, 0.0), now=0.25)
    assert len(tr.tracks) == 1 and tr.tracks[0].hits == 2
    snap = tr.snapshot(0.25)[0]
    assert snap["confirmed"] and not snap["stale"]


def test_tracker_handles_missing_and_bad_detections():
    tr = ObstacleTracker()
    tr.update([det("person", None), det("tv", 1.0), det("shelf", float("nan"))], (0, 0, 0), now=0.0)
    assert tr.tracks == [] and tr.rejected == 3
    tr.update([det("shelf", 2.0)], (0, 0, 0), now=0.0)
    assert tr.snapshot(STALE_AFTER + 0.1)[0]["stale"] is True
    tr.update([], (0, 0, 0), now=DROP_AFTER + 0.1)  # never re-observed -> dropped
    assert tr.tracks == []


def test_observation_mask_marks_rays_only():
    m = ObservationMask(rows=10, cols=10, resolution=1.0)
    m.mark_rays((0.5, 0.5), np.array([0.0]), np.array([4.0]))
    assert m.seen[0, :5].all()
    assert not m.seen[0, 6:].any()
    assert not m.seen[1:, :].any()
    assert 0 < m.coverage() < 0.1


def test_cell_states_include_unknown():
    g = OccupancyGrid(4, 4, 1.0).build([Obstacle("o", "crate", "rect", 2.5, 2.5, w=1, h=1)], 0.3)
    seen = np.zeros_like(g.blocked)
    seen[1, 1] = True
    rows = g.cell_states(seen)
    assert rows[2][2] == "#"
    assert rows[1][1] == "."
    assert "?" in "".join(rows)
