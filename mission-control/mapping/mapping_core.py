"""Dual-layer occupancy-grid mapping core.

Pure logic, no FastAPI/Redis/robot-client imports, so it is directly unit
testable: everything here takes/returns plain dataclasses and lists.

Two layers per grid cell:
  - floor  (traversability): log-odds occupancy grid, exposed as
    -1 unknown / 0 free / 100 occupied per CONVENTIONS.md's map schema.
  - walls  (vertical-obstacle height): 0..255, bucketed from LiDAR point
    height (z). Updated independently of the floor decision so a low
    curb and a floor-to-ceiling wall are distinguishable even though both
    may register as "occupied" on the floor layer.

Multi-level (stairs) support: since the wire schema (CONVENTIONS.md) has a
single top-level ``level_id`` per map, cells belonging to a different floor
are kept in a *separate* OccupancyGrid instead of being mixed into one grid
under a per-cell level field. ``MapStore`` holds one grid per detected
level and exposes the currently active one -- see mapping/app.py.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Sequence

# --- log-odds tuning ---------------------------------------------------
L_FREE = -0.4          # log-odds decrement applied to every free (ray-traced) cell
L_OCC = 0.85            # log-odds increment applied to a hit cell
L_MIN = -4.0
L_MAX = 4.0
L_DECIDE_THRESH = 1.0   # |log_odds| >= this before a cell is called free/occupied
                        # (schema: -1 unknown, 0 free, 100 occupied)

# Height range (meters, world/robot z) considered relevant for the FLOOR
# traversability layer -- a hit in this band means "something blocks the
# floor here" (furniture, low walls, legs of a table, ...). The WALL layer
# below is updated from every point regardless of height.
FLOOR_Z_MIN = -0.6
FLOOR_Z_MAX = 0.55

WALL_Z_MAX = 2.5        # meters; clamps the z -> 0..255 height-bucket mapping
WALL_Z_BASE_BUCKET = 30  # any hit gets at least this much weight in the wall layer

# Wall-height band heuristically treated as a ramp/stair edge rather than a
# solid wall -- callers (mapping's own explorer, and the navigation pillar)
# can use this to avoid treating a staircase as an impassable obstacle.
STAIR_WALL_MIN = 30
STAIR_WALL_MAX = 120

# Stair/level-change detector tuning.
PITCH_STAIR_THRESH = 0.12   # rad; sustained pitch magnitude suggesting a ramp/stairs
STAIR_SUSTAIN_S = 1.2        # seconds pitch must stay elevated before we call it a level change


@dataclass
class OccupancyGrid:
    resolution: float = 0.05
    origin_x: float = -5.0
    origin_y: float = -5.0
    width: int = 200
    height: int = 200
    level_id: str = "ground"
    log_odds: list = field(default_factory=list)   # internal float log-odds, len = width*height
    walls: list = field(default_factory=list)        # 0..255 int, len = width*height

    def __post_init__(self):
        n = self.width * self.height
        if not self.log_odds:
            self.log_odds = [0.0] * n
        if not self.walls:
            self.walls = [0] * n

    def idx(self, gx: int, gy: int) -> int:
        return gy * self.width + gx

    def in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self.width and 0 <= gy < self.height

    def world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        gx = int(math.floor((x - self.origin_x) / self.resolution))
        gy = int(math.floor((y - self.origin_y) / self.resolution))
        return gx, gy

    def grid_to_world(self, gx: int, gy: int) -> tuple[float, float]:
        x = self.origin_x + (gx + 0.5) * self.resolution
        y = self.origin_y + (gy + 0.5) * self.resolution
        return x, y

    def clamp_cell(self, gx: int, gy: int) -> tuple[int, int]:
        return max(0, min(self.width - 1, gx)), max(0, min(self.height - 1, gy))

    def floor_cell(self, gx: int, gy: int) -> int:
        """-1 unknown, 0 free, 100 occupied -- per CONVENTIONS.md schema."""
        lo = self.log_odds[self.idx(gx, gy)]
        if lo >= L_DECIDE_THRESH:
            return 100
        if lo <= -L_DECIDE_THRESH:
            return 0
        return -1

    def floor_layer(self) -> list[int]:
        return [self.floor_cell(i % self.width, i // self.width) for i in range(self.width * self.height)]

    def coverage_stats(self) -> tuple[int, float]:
        """Returns (cells_explored, coverage_percent) -- explored == not unknown."""
        total = self.width * self.height
        explored = sum(1 for lo in self.log_odds if abs(lo) >= L_DECIDE_THRESH)
        pct = (explored / total * 100.0) if total else 0.0
        return explored, pct

    def to_schema_dict(self) -> dict:
        """Exactly the map schema from CONVENTIONS.md."""
        return {
            "resolution": self.resolution,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "width": self.width,
            "height": self.height,
            "level_id": self.level_id,
            "floor": self.floor_layer(),
            "walls": list(self.walls),
        }


class MapStore:
    """Holds one OccupancyGrid per detected building level.

    GET /map always serves the *active* level's grid, in the exact schema
    from CONVENTIONS.md (a single top-level ``level_id`` string) -- other
    already-seen levels stay addressable via ``get(level_id=...)`` without
    ever being mixed into the active grid.
    """

    def __init__(self, resolution: float = 0.05, width: int = 200, height: int = 200,
                 origin_x: float = -5.0, origin_y: float = -5.0):
        self._kwargs = dict(resolution=resolution, width=width, height=height,
                             origin_x=origin_x, origin_y=origin_y)
        self.active_level = "ground"
        self.levels: dict[str, OccupancyGrid] = {"ground": OccupancyGrid(level_id="ground", **self._kwargs)}

    @property
    def grid(self) -> OccupancyGrid:
        return self.levels[self.active_level]

    def get(self, level_id: Optional[str] = None) -> Optional[OccupancyGrid]:
        return self.levels.get(level_id) if level_id else self.grid

    def new_level(self) -> str:
        n = sum(1 for k in self.levels if k.startswith("level_"))
        level_id = f"level_{n + 1}"
        self.levels[level_id] = OccupancyGrid(level_id=level_id, **self._kwargs)
        self.active_level = level_id
        return level_id


def bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Integer Bresenham ray from (x0,y0) to (x1,y1) inclusive of both ends."""
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def height_bucket(z: float) -> int:
    z = max(0.0, min(z, WALL_Z_MAX))
    scaled = int(round((z / WALL_Z_MAX) * (255 - WALL_Z_BASE_BUCKET)))
    return min(255, WALL_Z_BASE_BUCKET + scaled)


def integrate_scan(grid: OccupancyGrid, robot_x: float, robot_y: float,
                    points: Sequence[tuple[float, float, float]]) -> None:
    """Ray-traces every LiDAR point from the robot's current cell out to the
    point's cell (Bresenham), decrementing log-odds of every free cell the
    ray passes through and incrementing the endpoint's log-odds *iff* the
    point falls in the floor-relevant height band. The wall layer is
    updated from every point's height bucket regardless of the floor
    decision -- so a shelf at 1.2m still shows up as a tall obstacle even
    though it doesn't block the floor layer at ground level.

    Note: both the mock and live robot_client backends return LiDAR points
    already in map/world coordinates (not robot-relative, despite
    RobotClient's abstract docstring), so no extra pose rotation is applied
    here -- see core/mock_client.py and core/live_client.py.
    """
    rgx, rgy = grid.world_to_grid(robot_x, robot_y)
    rgx, rgy = grid.clamp_cell(rgx, rgy)
    for px, py, pz in points:
        pgx, pgy = grid.world_to_grid(px, py)
        pgx, pgy = grid.clamp_cell(pgx, pgy)
        cells = bresenham_line(rgx, rgy, pgx, pgy)
        for cx, cy in cells[:-1]:
            i = grid.idx(cx, cy)
            grid.log_odds[i] = max(L_MIN, grid.log_odds[i] + L_FREE)
        i = grid.idx(pgx, pgy)
        if FLOOR_Z_MIN <= pz <= FLOOR_Z_MAX:
            grid.log_odds[i] = min(L_MAX, grid.log_odds[i] + L_OCC)
        bucket = height_bucket(pz)
        if bucket > grid.walls[i]:
            grid.walls[i] = bucket


def _neighbors4(gx: int, gy: int):
    yield gx + 1, gy
    yield gx - 1, gy
    yield gx, gy + 1
    yield gx, gy - 1


def next_frontier_target(grid: OccupancyGrid, start_gx: int, start_gy: int
                          ) -> Optional[tuple[tuple[int, int], list[tuple[int, int]]]]:
    """Single BFS over reachable free cells starting at the robot's cell.

    Returns ``(target_cell, path)`` for the *nearest* reachable frontier
    cell (a free cell touching at least one unknown cell), where ``path``
    is the list of grid cells from start to target inclusive -- or
    ``None`` if no reachable frontier remains (exploration complete).
    BFS visits nearest-first, so the first frontier found is the nearest.
    """
    start = (start_gx, start_gy)
    visited = {start}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    q = deque([start])
    while q:
        cur = q.popleft()
        gx, gy = cur
        touches_unknown = False
        for nx, ny in _neighbors4(gx, gy):
            if grid.in_bounds(nx, ny) and grid.floor_cell(nx, ny) == -1:
                touches_unknown = True
                break
        if touches_unknown and cur != start:
            return cur, _reconstruct(came_from, start, cur)
        for nx, ny in _neighbors4(gx, gy):
            npos = (nx, ny)
            if not grid.in_bounds(nx, ny) or npos in visited:
                continue
            if grid.floor_cell(nx, ny) == 0:
                visited.add(npos)
                came_from[npos] = cur
                q.append(npos)
    return None


def _reconstruct(came_from: dict, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    path = [goal]
    cur = goal
    while cur != start:
        cur = came_from[cur]
        path.append(cur)
    path.reverse()
    return path


class StairDetector:
    """Heuristic level-change detector.

    A sustained pitch excursion (climbing/descending) that settles back to
    roughly level is taken as evidence the robot moved to a different
    floor. Deliberately simple -- good enough to tag newly-explored cells
    with a new level_id instead of silently mixing two floors' geometry
    into one grid, or crashing.
    """

    def __init__(self):
        self._excursion_since: Optional[float] = None

    def update(self, pitch: float, now: Optional[float] = None) -> bool:
        """Feed the latest IMU pitch. Returns True exactly once, the
        instant a sustained climb/descent has just finished (caller should
        start a new level)."""
        now = time.time() if now is None else now
        climbing = abs(pitch) >= PITCH_STAIR_THRESH
        if climbing:
            if self._excursion_since is None:
                self._excursion_since = now
            return False
        if self._excursion_since is not None:
            duration = now - self._excursion_since
            self._excursion_since = None
            return duration >= STAIR_SUSTAIN_S
        return False
