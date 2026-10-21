import math

import numpy as np
import pytest

from app.mapping.occupancy import (
    FREE,
    OCCUPIED,
    UNKNOWN,
    LogOddsMap,
    MapFormatError,
    parse_pgm,
    parse_yaml,
    resample,
    states_from_image,
)
from app.mapping.slam import ScanMatcher, compose, relative
from app.simulation.engine import CommandError
from conftest import run_until


def test_single_ray_marks_free_then_occupied():
    m = LogOddsMap(10, 10, 0.1)
    # One ray along +x from (1, 5) hitting something at 3 m.
    m.integrate((1.0, 5.0, 0.0), [0.0], [3.0], max_range=8.0)
    s = m.states()
    row = 50
    assert s[row, 15] == FREE and s[row, 35] == FREE  # along the ray
    assert s[row, 40] == OCCUPIED  # end point (x = 4.0)
    assert s[row, 45] == UNKNOWN  # beyond the hit: never seen
    assert s[70, 15] == UNKNOWN  # off the ray


def test_no_return_frees_up_to_max_range_only():
    m = LogOddsMap(10, 10, 0.1)
    m.integrate((1.0, 5.0, 0.0), [0.0], [np.nan], max_range=2.0)
    s = m.states()
    assert s[50, 25] == FREE and s[50, 35] == UNKNOWN
    assert (s == OCCUPIED).sum() == 0


def test_pose_algebra_round_trip():
    a, b = (1.0, 2.0, 0.5), (3.0, -1.0, 2.0)
    back = compose(a, relative(a, b))
    assert all(math.isclose(p, q, abs_tol=1e-9) for p, q in zip(back, b))


def test_scan_matcher_recovers_an_offset_pose():
    # Map an L-shaped corner from the true pose, then match from a wrong guess.
    m = LogOddsMap(10, 10, 0.1)
    # Walls on cell centres: the map stores a surface at the centre of the cell it falls
    # in, so matching is only accurate to half a cell (5 cm here) for arbitrary walls.
    walls = []
    for i in range(60):
        walls.append((2.0 + i * 0.1, 8.05))
        walls.append((8.05, 2.0 + i * 0.1))
    true = (5.0, 5.0, 0.0)
    ang = np.array([math.atan2(y - true[1], x - true[0]) for x, y in walls])
    rng = np.array([math.hypot(x - true[0], y - true[1]) for x, y in walls])
    for _ in range(3):
        m.integrate(true, ang, rng, 8.0)
    guess = (5.09, 4.93, math.radians(2.0))
    # Ray angles as the sensor reports them: relative to the robot's (true) heading.
    pose, score, used = ScanMatcher().match(m, guess, ang - true[2], rng)
    assert used and score > 0.5
    assert math.hypot(pose[0] - true[0], pose[1] - true[1]) < 0.04
    assert abs(pose[2] - true[2]) < math.radians(1.0)


def test_pgm_yaml_round_trip():
    m = LogOddsMap(2.0, 1.0, 0.1)
    m.integrate((0.2, 0.5, 0.0), [0.0], [1.0], max_range=3.0)
    meta = parse_yaml(m.to_yaml("map.pgm"))
    assert meta["resolution"] == 0.1 and meta["origin"][:2] == [0.0, 0.0]
    states = states_from_image(parse_pgm(m.to_pgm()), meta)
    assert np.array_equal(states, m.states())


def test_map_format_errors():
    with pytest.raises(MapFormatError):
        parse_yaml("image: map.pgm\norigin: [0, 0, 0]\n")  # no resolution
    with pytest.raises(MapFormatError):
        parse_yaml("resolution: 5\norigin: [0, 0, 0]\n")  # absurd resolution
    with pytest.raises(MapFormatError):
        parse_pgm(b"P6\n2 2\n255\n" + b"\x00" * 12)  # colour PPM, not PGM
    with pytest.raises(MapFormatError):
        parse_pgm(b"P5\n4 4\n255\n\x00\x00")  # truncated


def test_resample_keeps_thin_walls():
    states = np.full((10, 10), FREE, dtype=np.uint8)
    states[:, 5] = OCCUPIED  # one 0.1 m wide wall
    occ, unknown = resample(states, 0.1, (0.0, 0.0), 5, 5, 0.2)
    assert occ[:, 2].all() and not unknown.any()


def test_slam_tracks_the_robot_and_beats_odometry(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    assert run_until(engine, {"goal_reached"}, max_seconds=60)
    ms = engine.mapping_status()
    assert ms["scans"] > 100 and ms["known_fraction"] > 0.5
    assert ms["localization"]["quality"] in ("good", "fair")
    assert ms["pose_error_m"] < 0.25  # measured against the simulator ground truth


def test_exploration_maps_the_warehouse_without_collisions(engine):
    engine.params["moving_obstacles"] = False
    engine.explore()
    assert engine.params["planner_map"] == "slam"
    for _ in range(int(150 / engine.dt)):
        engine.step()
        if not engine.exploring and engine.status not in ("planning", "navigating", "replanning"):
            break
    assert not engine.exploring
    assert engine.status == "idle" and "Exploration finished" in engine.status_reason
    assert engine.mapping_status()["known_fraction"] > 0.6
    assert engine.collisions == 0


def test_navigation_on_saved_and_imported_map(engine, tmp_path):
    engine.maps_dir = tmp_path
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    assert run_until(engine, {"goal_reached"}, max_seconds=60)
    saved = engine.save_map("aisle")
    assert (tmp_path / "aisle.pgm").is_file() and saved["occupied_cells"] > 0
    assert engine.list_maps()[0]["name"] == "aisle"
    engine.reset("warehouse")
    engine.load_map("aisle")
    engine.set_planner_map("imported")
    # Unknown space in an imported map is not driveable; the mapped aisle is.
    engine.set_target(10.0, 6.0)
    engine.navigate()
    assert run_until(engine, {"goal_reached"}, max_seconds=60)
    assert engine.collisions == 0
    with pytest.raises(CommandError) as err:
        engine.set_target(10.0, 11.4)  # never observed from the aisle
    assert err.value.code == "target_unsafe"


def test_lidar_off_reports_no_lidar(engine):
    engine.configure_sensor("lidar", enabled=False)
    for _ in range(5):
        engine.step()
    ms = engine.mapping_status()
    assert ms["state"] == "no_lidar"
    assert ms["localization"]["quality"] == "dead_reckoning"
    with pytest.raises(CommandError) as err:
        engine.explore()
    assert err.value.code == "no_lidar"


def test_imported_map_requires_a_map(engine):
    with pytest.raises(CommandError) as err:
        engine.set_planner_map("imported")
    assert err.value.code == "no_imported_map"
