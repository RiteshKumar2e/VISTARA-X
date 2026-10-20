import math

import numpy as np
import pytest

from app.sensors.models import Imu, Lidar, Ultrasonic, WheelOdometry, cast_rays
from app.sensors.suite import SensorSuite
from app.simulation.engine import CommandError
from app.simulation.world import Obstacle, RobotState, World
from conftest import run_until

WALL = Obstacle("wall", "barrier", "rect", 6.0, 5.0, w=0.4, h=4.0)


def world_with(obstacles, x=2.0, y=5.0, theta=0.0):
    return World(10.0, 10.0, RobotState(x, y, theta), list(obstacles))


def test_cast_rays_hits_geometry_and_boundary():
    d, idx = cast_rays(2.0, 5.0, np.array([0.0, math.pi]), [WALL], 10, 10, 20)
    assert d[0] == pytest.approx(3.8, abs=1e-6) and idx[0] == 0  # wall face at x = 5.8
    assert d[1] == pytest.approx(2.0, abs=1e-6) and idx[1] == -1  # map boundary at x = 0
    d, idx = cast_rays(2.0, 5.0, np.array([0.0]), [WALL], 10, 10, 3.0)
    assert idx[0] == -2  # beyond max range: no return


def test_lidar_scan_matches_geometry_within_noise():
    lidar = Lidar("lidar", "LiDAR", "range_scan", rate_hz=10, noise_std=0.01)
    w = world_with([WALL])
    ranges = lidar.measure((2.0, 5.0, 0.0), w.obstacles, w.width, w.height, 0.0)
    straight = len(ranges) // 2  # 0 deg relative bearing
    assert ranges[straight] == pytest.approx(3.8, abs=0.05)
    r = lidar.reading
    assert r["front_min"] == pytest.approx(3.8, abs=0.05)
    assert r["valid_returns"] > 0 and len(r["scan"]) == r["rays"]
    lidar.configure({"max_range": 3.0})
    ranges = lidar.measure((2.0, 5.0, 0.0), w.obstacles, w.width, w.height, 0.1)
    assert math.isnan(ranges[straight])  # out of the configured range


def test_ultrasonic_channels():
    us = Ultrasonic("ultrasonic", "US", "proximity", rate_hz=10, max_range=2.0)
    w = world_with([WALL], x=5.0)
    r = us.measure((5.0, 5.0, 0.0), w.obstacles, w.width, w.height, 0.0)
    front = next(c for c in r["channels"] if c["bearing_deg"] == 0.0)
    # Wall face at x = 5.8, sensor on the chassis edge at x = 5.3.
    assert front["detected"] and front["range"] == pytest.approx(0.5, abs=0.05)
    back = next(c for c in r["channels"] if c["bearing_deg"] == 180.0)
    assert not back["detected"] and back["range"] is None


def test_imu_and_odometry_are_noisy_estimates_not_ground_truth():
    imu = Imu("imu", "IMU", "inertial", rate_hz=20)
    odo = WheelOdometry("odometry", "Odo", "odometry", rate_hz=20)
    robot = RobotState(0.0, 0.0, 0.0, v=0.8, w=0.2)
    for i in range(200):
        robot.theta += robot.w * 0.05
        robot.x += robot.v * math.cos(robot.theta) * 0.05
        robot.y += robot.v * math.sin(robot.theta) * 0.05
        imu.measure(robot, 0.05, i * 0.05)
        odo.measure(robot, 0.05, i * 0.05)
    assert imu.reading["yaw_drift_deg"] != 0.0  # bias integrates into drift
    assert 0.0 < odo.reading["drift_m"] < 1.0
    assert odo.reading["ticks_left"] < odo.reading["ticks_right"]  # turning left


def test_sensor_health_states():
    lidar = Lidar("lidar", "LiDAR", "range_scan", rate_hz=10)
    assert lidar.status(0.0)["health"] == "waiting"
    w = world_with([WALL])
    lidar.measure((2.0, 5.0, 0.0), w.obstacles, w.width, w.height, 0.0)
    assert lidar.status(0.1)["health"] == "ok"
    assert lidar.status(2.0)["health"] == "stale"
    lidar.enabled = False
    assert lidar.status(2.0)["health"] == "disabled"
    assert lidar.status(2.0)["simulated"] is True


def test_proximity_decisions_and_degraded_mode():
    suite = SensorSuite((50, 50), 0.2)
    robot = RobotState(5.0, 5.0, 0.0)
    for x, expected in [(5.4, "stop"), (4.9, "slow"), (3.0, "clear")]:
        w = world_with([WALL], x=x)
        suite.reset()
        suite.step(w, 0.05, 1.0)
        d = suite.proximity(w.robot, corridor_length=5.0)
        assert d["action"] == expected, (x, d)
        assert "lidar" in d["sources"]
    # Obstacles beside the corridor must not trigger a stop.
    side = Obstacle("side", "shelf", "rect", 6.0, 6.0, w=4.0, h=0.4)  # 0.8 m to the left of the path
    w = world_with([side], x=5.0)
    suite.reset()
    suite.step(w, 0.05, 1.0)
    assert suite.proximity(w.robot, 3.0)["action"] == "clear"
    # Both proximity sensors off -> explicit fail-safe speed.
    suite.configure("lidar", enabled=False)
    suite.configure("ultrasonic", enabled=False)
    d = suite.proximity(robot, 3.0)
    assert d["action"] == "degraded" and d["speed_factor"] == suite.policy.degraded_factor


def test_engine_proximity_stop_and_lidar_map(engine):
    engine.params["moving_obstacles"] = False
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    for _ in range(30):
        engine.step()
    r = engine.world.robot
    # Drop an obstacle just ahead, inside the corridor, before the grid check can replan.
    engine.add_obstacle(r.x + 0.95, r.y, size=0.4)
    for _ in range(3):  # stays within the 0.3 s replanning dwell; LiDAR samples at 10 Hz
        engine.step()
    # The simulated sensors measure the new obstacle inside the driving corridor...
    decision = engine.sensors.proximity(engine.world.robot, corridor_length=2.0)
    assert decision["action"] in ("slow", "stop") and decision["front_clearance"] < 0.9
    assert "lidar" in decision["sources"]
    # ...and the robot stops to replan instead of driving on.
    assert engine.status == "replanning" and engine.world.robot.v == 0.0
    assert engine.collisions == 0
    assert run_until(engine, {"goal_reached", "blocked"})
    assert engine.collisions == 0
    assert any("1" in row for row in engine.map_data()["grid"]["lidar_occupied"])


def test_engine_sensor_configuration_validation(engine):
    engine.configure_sensor("lidar", rate_hz=5, params={"fov_deg": 180, "max_range": 6})
    st = {s["key"]: s for s in engine.sensor_status()["sensors"]}
    assert st["lidar"]["config"]["fov_deg"] == 180 and st["lidar"]["rate_hz"] == 5
    assert {"camera", "depth", "lidar", "ultrasonic", "imu", "odometry"} <= set(st)
    assert all(s["simulated"] for s in st.values())
    with pytest.raises(CommandError):
        engine.configure_sensor("lidar", params={"max_range": 999})
    with pytest.raises(CommandError):
        engine.configure_sensor("lidar", params={"warp": 1})
    with pytest.raises(CommandError):
        engine.configure_sensor("safety", params={"stop_distance": 1.0, "slow_distance": 0.5})
    engine.configure_sensor("safety", params={"slow_distance": 1.2, "stop_distance": 0.4})
    assert engine.sensors.policy.stop_distance == 0.4


def test_mission_completes_with_proximity_sensors_disabled(engine):
    engine.params["moving_obstacles"] = False
    engine.configure_sensor("lidar", enabled=False)
    engine.configure_sensor("ultrasonic", enabled=False)
    engine.set_target(18.5, 6.0)
    engine.navigate()
    run_until(engine, {"navigating"})
    for _ in range(40):
        engine.step()
    assert engine.world.robot.v <= engine.params["max_speed"] * 0.31  # fail-safe speed
    assert any(e["type"] == "proximity" and "fail-safe" in e["message"] for e in engine.events)
    assert run_until(engine, {"goal_reached", "blocked"}, max_seconds=180)
    assert engine.status == "goal_reached" and engine.collisions == 0
