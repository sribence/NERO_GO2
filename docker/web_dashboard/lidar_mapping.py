"""Pure, dependency-light occupancy-grid accumulation logic for the live
Hesai LiDAR map ("Robotporszívó mód").

Extracted out of app.py on 2026-09-17 so the grid math is unit-testable
without importing app.py (which starts several background threads and a
Flask app at import time — not something a test process should trigger).

This module owns ONLY the math: world<->cell conversion, the Bresenham
log-odds update, deriving the tri-state grid from log-odds, and saving a
PNG snapshot to disk. It has NO knowledge of the robot SDK, Flask, or the
hesai_bridge HTTP API — app.py still owns fetching the live LiDAR points
and robot pose and calls into these functions.

The 90-degree Hesai extrinsic yaw correction found empirically on
2026-09-04 (ld. docs/15-munkamenet-naplo-2026-09-04.md) lives in app.py as
LIVE_MAP_YAW_OFFSET, applied when rotating LiDAR points into world frame
BEFORE they ever reach this module — this module just consumes already
world-frame (x, y) points and does not re-apply or duplicate that
correction.
"""

from __future__ import annotations

import math
import os
import time

import numpy as np

# --- Log-odds tuning (mirrors app.py's LOGODDS_* constants) ---------------
LOGODDS_HIT = 0.85
LOGODDS_MISS = -0.4
LOGODDS_MIN = -5.0
LOGODDS_MAX = 5.0
LOGODDS_OCC_THRESH = 2.0
LOGODDS_FREE_THRESH = -2.0


def world_to_cell(wx, wy, origin_x, origin_y, resolution):
    """World-frame meters -> integer grid-cell indices."""
    return int((wx - origin_x) / resolution), int((wy - origin_y) / resolution)


def bresenham_update_logodds(
    log_odds,
    x0,
    y0,
    x1,
    y1,
    hit=LOGODDS_HIT,
    miss=LOGODDS_MISS,
    lo_min=LOGODDS_MIN,
    lo_max=LOGODDS_MAX,
):
    """Walks the line from (x0,y0) [robot cell] to (x1,y1) [LiDAR hit cell],
    nudging every intermediate cell towards "free" (LOGODDS_MISS) and the
    endpoint towards "occupied" (LOGODDS_HIT), saturating to [lo_min, lo_max].
    In-place on `log_odds`. Cells outside the grid bounds are silently
    skipped (caller is expected to have already bounds-checked the
    endpoints, but the walk itself may still pass through out-of-range
    cells for a line that clips the grid edge)."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    h, w = log_odds.shape
    x, y = x0, y0
    while True:
        if 0 <= x < w and 0 <= y < h:
            is_endpoint = x == x1 and y == y1
            delta = hit if is_endpoint else miss
            log_odds[y, x] = min(lo_max, max(lo_min, log_odds[y, x] + delta))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


def grid_from_logodds(log_odds, occ_thresh=LOGODDS_OCC_THRESH, free_thresh=LOGODDS_FREE_THRESH):
    """Derives the tri-state grid (-1 unknown / 0 free / 100 occupied) fresh
    from the persistent log_odds array. Returns a new int16 array — does not
    mutate log_odds."""
    grid = np.full(log_odds.shape, -1, dtype=np.int16)
    grid[log_odds >= occ_thresh] = 100
    grid[log_odds <= free_thresh] = 0
    return grid


def integrate_scan(log_odds, robot_x, robot_y, world_points_xy, origin_x, origin_y, resolution):
    """Accumulates ONE LiDAR scan into the persistent `log_odds` array
    (in-place) and returns the freshly-derived tri-state grid.

    `world_points_xy` is an (N, 2) array-like of already world-frame LiDAR
    point (x, y) coordinates (any per-sensor extrinsic rotation, like the
    Hesai 90-degree yaw offset, must already be applied by the caller).
    Points and the robot pose that fall outside the grid are skipped, not
    an error — this is what keeps the grid a fixed-size buffer.

    This is the pure equivalent of app.py's `_live_map_update_once` inner
    loop (everything after the HTTP fetch + roll/pitch/z filtering), kept
    separate so the accumulation-over-time behaviour (this function called
    repeatedly with different scans) is directly unit-testable with
    synthetic points and no LiDAR hardware."""
    cells = log_odds.shape[0]
    rcx, rcy = world_to_cell(robot_x, robot_y, origin_x, origin_y, resolution)
    pts = np.asarray(world_points_xy, dtype=np.float64).reshape(-1, 2)
    if 0 <= rcx < cells and 0 <= rcy < cells:
        for wx, wy in pts:
            pcx, pcy = world_to_cell(wx, wy, origin_x, origin_y, resolution)
            if 0 <= pcx < cells and 0 <= pcy < cells:
                bresenham_update_logodds(log_odds, rcx, rcy, pcx, pcy)
    return grid_from_logodds(log_odds)


def save_grid_snapshot_png(grid, path):
    """Persists the current tri-state grid to disk as a greyscale PNG:
    unknown(-1) -> mid-grey 127, free(0) -> white 255, occupied(100) -> black 0
    (matches the usual ROS/SLAM occupancy-grid visual convention). Uses
    OpenCV (already a project dependency, ld. requirements.txt) rather than
    adding Pillow. Creates the destination directory if missing. Returns
    the path on success, None on failure (never raises — this runs on a
    periodic background timer and a transient disk/permission hiccup
    should not take down the live-map thread)."""
    try:
        import cv2  # local import: keeps this module importable in tests
        # even in an environment without opencv installed, as long as the
        # snapshot-saving test isn't the one running.
    except ImportError:
        return None

    img = np.full(grid.shape, 127, dtype=np.uint8)  # unknown = grey
    img[grid == 0] = 255  # free = white
    img[grid == 100] = 0  # occupied = black
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ok = cv2.imwrite(path, img)
        return path if ok else None
    except OSError:
        return None


class SnapshotScheduler:
    """Tiny stateful helper: "has enough wall-clock time passed since the
    last snapshot save?" Kept separate from time.sleep()-based polling so
    it's testable without actually waiting."""

    def __init__(self, interval_s, clock=time.time):
        self.interval_s = interval_s
        self._clock = clock
        self._last = None

    def due(self):
        now = self._clock()
        if self._last is None or (now - self._last) >= self.interval_s:
            self._last = now
            return True
        return False
