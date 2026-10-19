import math

from app.navigation.astar import astar, path_length, plan
from app.navigation.grid import OccupancyGrid
from app.simulation.world import Obstacle


def make_grid(obstacles, inflation=0.45):
    return OccupancyGrid(20, 12, 0.2).build(obstacles, inflation)


def sample(path, n=20):
    for a, b in zip(path, path[1:]):
        for i in range(n + 1):
            t = i / n
            yield (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def test_straight_line_in_open_space():
    res = plan(make_grid([]), (2.0, 6.0), (18.0, 6.0))
    assert res.success
    assert res.waypoints[0] == (2.0, 6.0) and res.waypoints[-1] == (18.0, 6.0)
    assert len(res.waypoints) == 2  # smoothing removes redundant cells
    assert math.isclose(res.length, 16.0, abs_tol=1e-6)


def test_route_avoids_obstacle_and_stays_free():
    wall = Obstacle("w", "barrier", "rect", 10.0, 5.0, w=0.6, h=10.0)
    g = make_grid([wall])
    res = plan(g, (2.0, 5.0), (18.0, 5.0))
    assert res.success
    assert len(res.waypoints) > 2
    for a, b in zip(res.waypoints, res.waypoints[1:]):
        assert g.segment_free(*a, *b)
    # Every point on the route keeps more than the robot radius from the wall.
    assert all(float(wall.distance(*p)) > 0.3 for p in sample(res.waypoints))
    assert res.length > 16.0


def test_unreachable_goal_reports_no_path():
    walls = [
        Obstacle("n", "barrier", "rect", 15, 8, w=4, h=0.4),
        Obstacle("s", "barrier", "rect", 15, 4, w=4, h=0.4),
        Obstacle("w", "barrier", "rect", 13, 6, w=0.4, h=4.4),
        Obstacle("e", "barrier", "rect", 17, 6, w=0.4, h=4.4),
    ]
    res = plan(make_grid(walls), (2.0, 6.0), (15.0, 6.0))
    assert not res.success
    assert res.reason == "no_path"
    assert res.expanded > 0


def test_goal_inside_obstacle():
    res = plan(make_grid([Obstacle("o", "crate", "rect", 10, 6, w=2, h=2)]), (2.0, 6.0), (10.0, 6.0))
    assert not res.success and res.reason == "goal_blocked"


def test_no_diagonal_corner_cutting():
    g = OccupancyGrid(1.0, 1.0, 0.2)
    g.blocked[0, 1] = True  # cell right of start
    g.blocked[1, 0] = True  # cell above start
    res = astar(g, (0, 0), (1, 1))
    assert not res.success  # the only diagonal squeezes between two blocked cells


def test_astar_is_optimal_on_open_grid():
    g = OccupancyGrid(2.0, 2.0, 0.2)
    res = astar(g, (0, 0), (0, 9))
    assert res.success and len(res.cells) == 10


def test_start_inside_inflation_recovers():
    g = make_grid([Obstacle("o", "crate", "rect", 5, 6, w=1, h=1)])
    # 0.2 m from the surface is inside the inflated zone, but planning still succeeds.
    assert plan(g, (5.7, 6.0), (15.0, 6.0)).success


def test_path_length():
    assert path_length([(0, 0), (3, 4), (3, 10)]) == 11
