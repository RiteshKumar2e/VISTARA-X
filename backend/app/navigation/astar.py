"""A* search on an 8-connected occupancy grid with an octile heuristic.

Diagonal moves are only allowed when both adjacent orthogonal cells are free, so
the robot never cuts the corner of an inflated obstacle.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

from .grid import OccupancyGrid

SQRT2 = math.sqrt(2.0)
CAUTION_PENALTY = 0.8  # extra cost (in cells) for entering the caution band
_NEIGHBOURS = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, SQRT2),
    (1, -1, SQRT2),
    (-1, 1, SQRT2),
    (-1, -1, SQRT2),
]


@dataclass
class PlanResult:
    success: bool
    reason: str = ""
    cells: list[tuple[int, int]] = field(default_factory=list)
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    expanded: int = 0
    length: float = 0.0  # metres along the smoothed waypoints


def _octile(a: tuple[int, int], b: tuple[int, int]) -> float:
    dr, dc = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (dr + dc) + (SQRT2 - 2.0) * min(dr, dc)


def astar(grid: OccupancyGrid, start: tuple[int, int], goal: tuple[int, int]) -> PlanResult:
    if not grid.is_free(*start):
        return PlanResult(False, "start_blocked")
    if not grid.is_free(*goal):
        return PlanResult(False, "goal_blocked")
    if start == goal:
        return PlanResult(True, cells=[start])

    open_heap: list[tuple[float, float, tuple[int, int]]] = [(_octile(start, goal), 0.0, start)]
    g_score = {start: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()
    expanded = 0

    while open_heap:
        _, g, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            cells = [current]
            while current in came_from:
                current = came_from[current]
                cells.append(current)
            cells.reverse()
            return PlanResult(True, cells=cells, expanded=expanded)
        closed.add(current)
        expanded += 1
        r, c = current
        for dr, dc, cost in _NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if not grid.is_free(nr, nc) or (nr, nc) in closed:
                continue
            if dr and dc and not (grid.is_free(r + dr, c) and grid.is_free(r, c + dc)):
                continue
            ng = g + cost + (CAUTION_PENALTY if grid.caution[nr, nc] else 0.0)
            if ng < g_score.get((nr, nc), float("inf")):
                g_score[(nr, nc)] = ng
                came_from[(nr, nc)] = current
                heapq.heappush(open_heap, (ng + _octile((nr, nc), goal), ng, (nr, nc)))

    return PlanResult(False, "no_path", expanded=expanded)


def smooth_path(grid: OccupancyGrid, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Greedy line-of-sight shortcutting. Keeps only waypoints that are needed.

    A shortcut must not enter the caution band unless the raw A* route already
    passed through it between those points (e.g. a narrow aisle)."""
    if len(points) <= 2:
        return list(points)
    in_caution = [grid.caution[grid.world_to_cell(*p)] for p in points]
    out = [points[0]]
    i = 0
    while i < len(points) - 1:
        j = len(points) - 1
        while j > i + 1:
            strict = not any(in_caution[i : j + 1])
            if grid.segment_free(*points[i], *points[j], strict=strict):
                break
            j -= 1
        out.append(points[j])
        i = j
    return out


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[k], points[k + 1]) for k in range(len(points) - 1))


def plan(
    grid: OccupancyGrid,
    start_xy: tuple[float, float],
    goal_xy: tuple[float, float],
) -> PlanResult:
    """Plan in world coordinates. The start may sit slightly inside the inflated
    zone (e.g. after the margin changes), in which case we start from the nearest
    free cell; the goal must be free."""
    start = grid.world_to_cell(*start_xy)
    goal = grid.world_to_cell(*goal_xy)
    free_start = grid.nearest_free(*start)
    if free_start is None:
        return PlanResult(False, "start_blocked")
    result = astar(grid, free_start, goal)
    if not result.success:
        return result
    pts = [grid.cell_to_world(r, c) for r, c in result.cells]
    # Use exact start/goal positions rather than cell centres.
    pts[0] = start_xy
    pts[-1] = goal_xy
    if len(pts) == 1:
        pts.append(goal_xy)
    result.waypoints = smooth_path(grid, pts)
    result.length = path_length(result.waypoints)
    return result
