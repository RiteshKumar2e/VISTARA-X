import math

import pytest

from app.simulation.engine import CommandError
from conftest import run_until


def drive(engine, seconds):
    for _ in range(int(seconds / engine.dt)):
        engine.step()


def test_initial_state(engine):
    snap = engine.snapshot()
    assert snap["mission"]["status"] == "idle"
    assert snap["target"] is None
    assert snap["path"] == []
    assert snap["scenario"] == "warehouse"


def test_navigate_requires_target(engine):
    with pytest.raises(CommandError) as err:
        engine.navigate()
    assert err.value.code == "no_target"


@pytest.mark.parametrize(
    "x,y,code",
    [(0.1, 6.0, "target_out_of_bounds"), (5.0, 9.5, "target_unsafe"), (10.0, 8.3, "target_unsafe")],
)
def test_target_validation(engine, x, y, code):
    with pytest.raises(CommandError) as err:
        engine.set_target(x, y)
    assert err.value.code == code


def test_mission_reaches_goal_without_collision(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    assert engine.status == "planning"
    engine.step()
    assert engine.status == "navigating"
    assert len(engine.path) >= 2
    assert run_until(engine, {"goal_reached", "blocked"})
    snap = engine.snapshot()
    assert snap["mission"]["status"] == "goal_reached"
    assert snap["distance_to_target"] <= 0.2
    assert snap["safety"]["collisions"] == 0
    assert any(e["type"] == "goal_reached" for e in snap["events"])


def test_dynamic_obstacle_triggers_replan(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    drive(engine, 2.0)
    old_path = list(engine.path)
    obstacle = engine.inject_on_route()
    assert obstacle["id"].startswith("user-")
    engine.step()
    assert engine.replans == 1
    assert engine.path != old_path
    # The new route keeps clear of the injected barrier.
    barrier = next(o for o in engine.world.obstacles if o.id == obstacle["id"])
    for a, b in zip(engine.path, engine.path[1:]):
        for i in range(11):
            t = i / 10
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            assert float(barrier.distance(*p)) > 0.3
    assert run_until(engine, {"goal_reached", "blocked"})
    assert engine.status == "goal_reached"
    assert engine.collisions == 0
    types = [e["type"] for e in engine.events]
    assert "obstruction" in types and "replanned" in types


def test_moving_person_does_not_cause_collision(engine):
    engine.set_target(18.5, 6.0)
    engine.navigate()
    assert run_until(engine, {"goal_reached", "blocked"}, max_seconds=180)
    assert engine.status == "goal_reached"
    assert engine.collisions == 0


def test_unreachable_target_is_blocked(engine):
    engine.reset("enclosed")
    engine.set_target(16.0, 6.0)
    engine.navigate()
    engine.step()
    snap = engine.snapshot()
    assert snap["mission"]["status"] == "blocked"
    assert "No collision-free route" in snap["mission"]["reason"]
    assert snap["robot"]["v"] == 0
    assert all(e["type"] != "goal_reached" for e in snap["events"])


def test_pause_resume_stop(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    drive(engine, 1.0)
    engine.pause()
    assert engine.status == "paused"
    pose = (engine.world.robot.x, engine.world.robot.y)
    drive(engine, 1.0)
    assert (engine.world.robot.x, engine.world.robot.y) == pose  # frozen while paused
    with pytest.raises(CommandError):
        engine.pause()
    engine.resume()
    assert engine.status == "planning"
    engine.step()
    assert engine.status == "navigating"
    drive(engine, 0.5)
    assert engine.world.robot.x > pose[0]
    engine.stop()
    assert engine.status == "stopped"
    assert engine.world.robot.v == 0
    with pytest.raises(CommandError):
        engine.stop()
    with pytest.raises(CommandError):
        engine.resume()


def test_cannot_start_twice(engine):
    engine.set_target(18.5, 6.0)
    engine.navigate()
    with pytest.raises(CommandError) as err:
        engine.navigate()
    assert err.value.code == "mission_active"


def test_target_change_mid_mission_replans(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    engine.set_target(2.0, 10.5)
    assert engine.status == "planning"
    engine.step()
    assert engine.status == "navigating"
    assert engine.path[-1] == (2.0, 10.5)


def test_reset_restores_scenario(engine):
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    drive(engine, 2.0)
    engine.add_obstacle(3.0, 9.0)
    engine.reset("warehouse")
    snap = engine.snapshot()
    assert snap["mission"]["status"] == "idle"
    assert snap["robot"]["x"] == 1.5 and snap["robot"]["y"] == 6.0
    assert not any(o["id"].startswith("user-") for o in snap["obstacles"])
    with pytest.raises(CommandError):
        engine.reset("nope")


def test_obstacle_validation(engine):
    with pytest.raises(CommandError) as err:
        engine.add_obstacle(1.6, 6.0)
    assert err.value.code == "too_close_to_robot"
    engine.set_target(18.5, 6.0)
    with pytest.raises(CommandError) as err:
        engine.add_obstacle(18.5, 6.0)
    assert err.value.code == "covers_target"
    with pytest.raises(CommandError) as err:
        engine.inject_on_route()
    assert err.value.code == "no_active_route"
    engine.add_obstacle(3.0, 9.0)
    assert engine.clear_obstacles() == 1


def test_sealing_the_only_route_gives_blocked(engine):
    engine.params["moving_obstacles"] = False
    engine.reset("enclosed")
    # Open the bay's east wall so a route exists, then seal it while driving.
    engine.world.obstacles = [o for o in engine.world.obstacles if o.id != "bay-e"]
    engine._grid_dirty = True
    engine.set_target(16.0, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    assert engine.status == "navigating"
    for y in (4.4, 6.0, 7.6):
        engine.add_obstacle(18.2, y, size=2.0, label="barrier")
    assert run_until(engine, {"blocked", "goal_reached"})
    assert engine.status == "blocked"
    assert engine.collisions == 0


def test_heading_is_wrapped(engine):
    engine.set_target(1.5, 10.5)
    engine.navigate()
    assert run_until(engine, {"goal_reached"})
    assert -math.pi <= engine.world.robot.theta <= math.pi


def test_move_added_obstacle(engine):
    engine.add_obstacle(3.0, 9.0)
    moved = engine.move_obstacle("user-1", 3.0, 10.0)
    assert moved["y"] == 10.0
    with pytest.raises(CommandError) as err:
        engine.move_obstacle("user-1", 1.6, 6.0)  # onto the robot: rejected, position kept
    assert err.value.code == "too_close_to_robot"
    assert next(o for o in engine.world.obstacles if o.id == "user-1").y == 10.0
    with pytest.raises(CommandError) as err:
        engine.move_obstacle("shelf-1", 3.0, 3.0)
    assert err.value.code == "not_movable"
    with pytest.raises(CommandError) as err:
        engine.move_obstacle("user-99", 3.0, 3.0)
    assert err.value.code == "not_found"


def test_planning_event_logged(engine):
    engine.set_target(18.5, 6.0)
    engine.navigate()
    engine.step()
    types = [e["type"] for e in engine.events]
    assert types.index("planning") < types.index("route_planned")


def test_add_standing_and_walking_person(engine):
    standing = engine.add_obstacle(3.0, 9.0, label="person")
    assert standing["label"] == "person" and standing["r"] == 0.3 and standing["height"] == 1.75
    assert standing["moving"] is False
    walker = engine.add_obstacle(12.0, 6.0, label="person", patrol_to=(12.0, 5.0))
    assert walker["moving"] is True
    start = next(o for o in engine.world.obstacles if o.id == walker["id"])
    y0 = start.y
    engine.set_target(18.5, 6.0)
    engine.navigate()
    for _ in range(40):  # people move only while a mission is active
        engine.step()
    assert start.y != y0
    with pytest.raises(CommandError) as err:
        engine.add_obstacle(10.0, 6.0, label="person", patrol_to=(10.0, 9.0))  # through shelf-3
    assert err.value.code == "invalid_patrol"
    with pytest.raises(CommandError):
        engine.add_obstacle(3.0, 9.0, label="crate", patrol_to=(3.0, 11.0))
    assert run_until(engine, {"goal_reached", "blocked"}, max_seconds=180)
    assert engine.collisions == 0


def test_obstacles_cannot_overlap(engine):
    engine.add_obstacle(3.0, 9.0)
    with pytest.raises(CommandError) as err:
        engine.add_obstacle(3.1, 9.1)
    assert err.value.code == "overlaps_obstacle"
    with pytest.raises(CommandError):
        engine.add_obstacle(5.0, 9.5)  # inside shelf-1
    engine.add_obstacle(3.0, 10.6)  # clear of both
