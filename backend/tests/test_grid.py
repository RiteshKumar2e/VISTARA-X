import math

import pytest

from app.navigation.grid import OccupancyGrid
from app.simulation.world import Obstacle


def test_world_cell_round_trip():
    g = OccupancyGrid(20, 12, 0.2)
    assert (g.rows, g.cols) == (60, 100)
    assert g.world_to_cell(0.0, 0.0) == (0, 0)
    assert g.world_to_cell(0.39, 0.21) == (1, 1)
    x, y = g.cell_to_world(1, 1)
    assert math.isclose(x, 0.3) and math.isclose(y, 0.3)
    # The far edge clamps into the grid instead of raising.
    assert g.world_to_cell(20.0, 12.0) == (59, 99)
    for r, c in [(0, 0), (17, 42), (59, 99)]:
        assert g.world_to_cell(*g.cell_to_world(r, c)) == (r, c)


def test_invalid_resolution():
    with pytest.raises(ValueError):
        OccupancyGrid(10, 10, 0)


def test_inflation_blocks_cells_around_obstacle():
    g = OccupancyGrid(10, 10, 0.2)
    obs = Obstacle("o", "crate", "rect", 5.0, 5.0, w=1.0, h=1.0)
    g.build([obs], inflation=0.5)
    assert g.occupied[g.world_to_cell(5.0, 5.0)]
    assert g.blocked[g.world_to_cell(5.0, 5.0)]
    # 0.4 m outside the surface is inside the 0.5 m inflation...
    assert g.blocked[g.world_to_cell(5.9, 5.0)]
    assert not g.occupied[g.world_to_cell(5.9, 5.0)]
    # ...1.5 m away is free.
    assert not g.blocked[g.world_to_cell(7.0, 5.0)]
    # The map boundary is inflated too.
    assert g.blocked[g.world_to_cell(0.1, 5.0)]


def test_caution_band_is_outside_blocked_zone():
    g = OccupancyGrid(10, 10, 0.2)
    g.build([Obstacle("o", "crate", "rect", 5.0, 5.0, w=1.0, h=1.0)], inflation=0.5, caution=0.3)
    assert not (g.caution & g.blocked).any()
    assert g.caution[g.world_to_cell(6.1, 5.0)]


def test_segment_free():
    g = OccupancyGrid(10, 10, 0.2)
    g.build([Obstacle("o", "crate", "rect", 5.0, 5.0, w=1.0, h=4.0)], inflation=0.4)
    assert not g.segment_free(2.0, 5.0, 8.0, 5.0)
    assert g.segment_free(2.0, 8.5, 8.0, 8.5)
