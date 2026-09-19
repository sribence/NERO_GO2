"""A* path planning over a 2D occupancy grid.

Pure, dependency-free (stdlib only) and testable in isolation: grid data in,
cell-path out. No FastAPI/robot/HTTP here -- see navigation/app.py for the
service wiring that fetches the map, calls this, and drives the robot.

Grid convention matches mapping's schema: row-major, index = gy*width+gx,
floor values -1 unknown / 0 free / 100 occupied.
"""
from __future__ import annotations

import heapq
import math
from typing import Optional, Sequence

SQRT2 = 2 ** 0.5

_NEIGHBORS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2),
)


def world_to_grid(x: float, y: float, origin_x: float, origin_y: float, resolution: float) -> tuple[int, int]:
    return int(math.floor((x - origin_x) / resolution)), int(math.floor((y - origin_y) / resolution))


def grid_to_world(gx: int, gy: int, origin_x: float, origin_y: float, resolution: float) -> tuple[float, float]:
    return origin_x + (gx + 0.5) * resolution, origin_y + (gy + 0.5) * resolution


def build_blocked_grid(floor: Sequence[int], walls: Sequence[int], width: int, height: int,
                        robot_radius_cells: int,
                        stair_wall_min: Optional[int] = None,
                        stair_wall_max: Optional[int] = None) -> list[bool]:
    """Builds the boolean "impassable" grid A* plans over.

    - Unknown (-1) cells are treated as passable (optimistic: don't let an
      incomplete map strand the robot with nowhere to go). Only cells the
      mapping pillar has actually confirmed occupied (100) are obstacles.
    - Obstacles are inflated by ``robot_radius_cells`` (a simple Chebyshev
      dilation) so the planned path keeps a safety margin from walls.
    - Cells whose wall-layer height bucket falls in the
      [stair_wall_min, stair_wall_max] band are treated as a ramp/stair
      edge: they are dropped from the inflation source set and cleared of
      inherited inflation, so A* is not walled off from a staircase by the
      safety margin around it. A cell the floor layer confirmed occupied
      (100) stays blocked regardless -- height alone must never re-open a
      known obstacle. Pass stair_wall_min/max as None to disable the
      heuristic entirely (the safe default, see navigation/app.py).
    """
    n = width * height
    is_stair = [False] * n
    if stair_wall_min is not None and stair_wall_max is not None:
        is_stair = [stair_wall_min <= w <= stair_wall_max for w in walls]

    # Every confirmed-occupied cell is an obstacle, stair band or not.
    obstacle = [floor[i] == 100 for i in range(n)]
    # ...but a stair cell does not *radiate* a safety margin, otherwise the
    # inflation around a staircase's own edge seals off the route onto it.
    inflation_source = [obstacle[i] and not is_stair[i] for i in range(n)]
    blocked = list(obstacle)
    if robot_radius_cells > 0:
        for gy in range(height):
            for gx in range(width):
                if not inflation_source[gy * width + gx]:
                    continue
                for dy in range(-robot_radius_cells, robot_radius_cells + 1):
                    for dx in range(-robot_radius_cells, robot_radius_cells + 1):
                        nx, ny = gx + dx, gy + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            blocked[ny * width + nx] = True
    # A stair cell may be cleared of *inflation* from a nearby obstacle, but
    # a cell the floor layer confirmed occupied is never freed on height
    # alone: the height band that reads as "stair" also covers every wall,
    # table leg and human leg below ~1m (AUDIT-2026-09-10.md, P0-1).
    for i in range(n):
        if is_stair[i] and floor[i] != 100:
            blocked[i] = False
    return blocked


def is_stair_cell(walls: Sequence[int], width: int, gx: int, gy: int,
                   stair_wall_min: int, stair_wall_max: int) -> bool:
    idx = gy * width + gx
    return stair_wall_min <= walls[idx] <= stair_wall_max


def nearest_free_cell(blocked: Sequence[bool], width: int, height: int,
                       start: tuple[int, int], max_radius: int = 20) -> Optional[tuple[int, int]]:
    """BFS spiral-out search for the nearest non-blocked cell to `start`
    (used to snap an occupied/unknown-adjacent start or goal onto the
    planning graph instead of failing outright)."""
    sx, sy = start
    if 0 <= sx < width and 0 <= sy < height and not blocked[sy * width + sx]:
        return start
    from collections import deque
    seen = {start}
    q = deque([start])
    steps = 0
    while q and steps < (2 * max_radius + 1) ** 2:
        gx, gy = q.popleft()
        steps += 1
        for dx, dy, _ in _NEIGHBORS:
            nx, ny = gx + dx, gy + dy
            if (nx, ny) in seen or not (0 <= nx < width and 0 <= ny < height):
                continue
            seen.add((nx, ny))
            if not blocked[ny * width + nx]:
                return nx, ny
            q.append((nx, ny))
    return None


def astar(width: int, height: int, blocked: Sequence[bool],
          start: tuple[int, int], goal: tuple[int, int]) -> Optional[list[tuple[int, int]]]:
    """Standard 8-connected A* with Euclidean heuristic. Returns a list of
    grid cells from start to goal inclusive, or None if unreachable."""
    if not (0 <= start[0] < width and 0 <= start[1] < height):
        return None
    if not (0 <= goal[0] < width and 0 <= goal[1] < height):
        return None
    if blocked[start[1] * width + start[0]] or blocked[goal[1] * width + goal[0]]:
        return None
    if start == goal:
        return [start]

    def h(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    open_heap = [(h(start, goal), 0.0, start)]
    came_from: dict = {}
    gscore = {start: 0.0}
    closed = set()

    while open_heap:
        _, g, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == goal:
            return _reconstruct(came_from, start, cur)
        closed.add(cur)
        cx, cy = cur
        for dx, dy, cost in _NEIGHBORS:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if blocked[ny * width + nx]:
                continue
            if dx != 0 and dy != 0:
                # don't let the path cut diagonally through a blocked corner
                if blocked[cy * width + nx] or blocked[ny * width + cx]:
                    continue
            npos = (nx, ny)
            if npos in closed:
                continue
            ng = g + cost
            if ng < gscore.get(npos, math.inf):
                gscore[npos] = ng
                came_from[npos] = cur
                heapq.heappush(open_heap, (ng + h(npos, goal), ng, npos))
    return None


def _reconstruct(came_from: dict, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    path = [goal]
    cur = goal
    while cur != start:
        cur = came_from[cur]
        path.append(cur)
    path.reverse()
    return path
