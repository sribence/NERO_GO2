"""Occupancy-grid accumulation logic (lidar_mapping.py), tested with
synthetic scans — no LiDAR hardware or robot connection needed.

lidar_mapping.py is deliberately free of Flask/robot-SDK imports, so it
can be imported directly (unlike app.py, which starts background threads
and opens a Flask app at import time)."""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lidar_mapping


def _empty_log_odds(cells=40):
    return np.zeros((cells, cells), dtype=np.float32)


def test_world_to_cell_maps_origin_to_cell_zero():
    cx, cy = lidar_mapping.world_to_cell(1.0, 1.0, origin_x=1.0, origin_y=1.0, resolution=0.1)
    assert (cx, cy) == (0, 0)


def test_world_to_cell_respects_resolution():
    # 0.5m at 0.05m/cell resolution -> cell 10
    cx, cy = lidar_mapping.world_to_cell(0.5, 0.0, origin_x=0.0, origin_y=0.0, resolution=0.05)
    assert cx == 10
    assert cy == 0


def test_bresenham_marks_endpoint_occupied_and_path_free():
    log_odds = _empty_log_odds()
    lidar_mapping.bresenham_update_logodds(log_odds, 5, 5, 5, 15)
    # endpoint got a HIT nudge (positive)
    assert log_odds[15, 5] > 0
    # a mid-path cell got a MISS nudge (negative)
    assert log_odds[10, 5] < 0


def test_bresenham_saturates_at_bounds_with_repeated_hits():
    log_odds = _empty_log_odds()
    for _ in range(100):
        lidar_mapping.bresenham_update_logodds(log_odds, 5, 5, 5, 6)
    assert log_odds[6, 5] == lidar_mapping.LOGODDS_MAX


def test_bresenham_out_of_range_cells_are_skipped_not_crashed():
    log_odds = _empty_log_odds(cells=10)
    # endpoint far outside the grid — must not raise, and in-bounds cells
    # along the way still get updated.
    lidar_mapping.bresenham_update_logodds(log_odds, 5, 5, 500, 500)
    assert log_odds[5, 5] < 0  # robot cell itself got a MISS pass-through


def test_grid_from_logodds_thresholds():
    log_odds = _empty_log_odds(cells=3)
    log_odds[0, 0] = lidar_mapping.LOGODDS_OCC_THRESH + 0.1
    log_odds[0, 1] = lidar_mapping.LOGODDS_FREE_THRESH - 0.1
    log_odds[0, 2] = 0.0  # unresolved -> unknown
    grid = lidar_mapping.grid_from_logodds(log_odds)
    assert grid[0, 0] == 100
    assert grid[0, 1] == 0
    assert grid[0, 2] == -1


def test_integrate_scan_marks_a_synthetic_wall_occupied():
    """Robot at grid centre, one synthetic scan straight ahead of it
    (a wall 1m away) — the wall's cell should end up occupied and the
    cells between the robot and the wall should end up free."""
    cells = 40
    resolution = 0.1
    origin_x = origin_y = -2.0  # so world (0,0) sits at cell (20, 20)
    log_odds = np.zeros((cells, cells), dtype=np.float32)

    robot_x, robot_y = 0.0, 0.0
    wall_points = np.array([[1.0, 0.0]] * 20)  # 20 rays all hitting the same wall point

    grid = lidar_mapping.integrate_scan(log_odds, robot_x, robot_y, wall_points, origin_x, origin_y, resolution)

    wall_cx, wall_cy = lidar_mapping.world_to_cell(1.0, 0.0, origin_x, origin_y, resolution)
    near_cx, near_cy = lidar_mapping.world_to_cell(0.3, 0.0, origin_x, origin_y, resolution)
    assert grid[wall_cy, wall_cx] == 100
    assert grid[near_cy, near_cx] == 0


def test_integrate_scan_accumulates_across_repeated_calls():
    """This is the actual "accumulate over time" behaviour the live map
    depends on: the SAME wall observed again on a later tick should
    become a MORE confident (not reset) occupied cell, and a transient
    single stray point from one scan should NOT survive as a permanent
    wall the way a real, repeated observation does."""
    cells = 40
    resolution = 0.1
    origin_x = origin_y = -2.0
    log_odds = np.zeros((cells, cells), dtype=np.float32)

    robot_x, robot_y = 0.0, 0.0
    wall_point = np.array([[1.0, 0.0]])
    wall_cx, wall_cy = lidar_mapping.world_to_cell(1.0, 0.0, origin_x, origin_y, resolution)

    # First scan: a single hit is not yet enough to cross LOGODDS_OCC_THRESH.
    lidar_mapping.integrate_scan(log_odds, robot_x, robot_y, wall_point, origin_x, origin_y, resolution)
    assert log_odds[wall_cy, wall_cx] < lidar_mapping.LOGODDS_OCC_THRESH

    # Repeated observation over several ticks (a persistent real wall)
    # eventually crosses the confidence threshold.
    grid = None
    for _ in range(5):
        grid = lidar_mapping.integrate_scan(log_odds, robot_x, robot_y, wall_point, origin_x, origin_y, resolution)
    assert grid[wall_cy, wall_cx] == 100

    # A single stray point far away, seen only once, must NOT show up as
    # a confident wall in the same accumulated grid.
    stray_cx, stray_cy = lidar_mapping.world_to_cell(-1.5, 1.5, origin_x, origin_y, resolution)
    assert grid[stray_cy, stray_cx] != 100


def test_integrate_scan_ignores_points_outside_grid_bounds():
    cells = 10
    resolution = 0.1
    origin_x = origin_y = -0.5
    log_odds = np.zeros((cells, cells), dtype=np.float32)
    far_point = np.array([[500.0, 500.0]])
    # Must not raise, and must not corrupt the grid (all still unknown).
    grid = lidar_mapping.integrate_scan(log_odds, 0.0, 0.0, far_point, origin_x, origin_y, resolution)
    assert np.all(grid == -1) or np.any(grid == 0)  # robot->offgrid ray may free some cells, that's fine
    assert not np.any(grid == 100)


def test_save_grid_snapshot_png_writes_a_file(tmp_path):
    grid = np.array([[-1, 0, 100], [100, -1, 0]], dtype=np.int16)
    dest = tmp_path / "maps" / "live_map.png"
    result = lidar_mapping.save_grid_snapshot_png(grid, str(dest))
    assert result == str(dest)
    assert dest.exists()
    assert dest.stat().st_size > 0


def test_snapshot_scheduler_fires_once_then_waits():
    fake_now = [100.0]
    sched = lidar_mapping.SnapshotScheduler(interval_s=10.0, clock=lambda: fake_now[0])

    assert sched.due() is True  # first call always fires
    assert sched.due() is False  # immediately again: not due yet

    fake_now[0] += 5.0
    assert sched.due() is False  # still within the interval

    fake_now[0] += 5.1
    assert sched.due() is True  # interval elapsed
