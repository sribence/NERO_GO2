"""Regression tests for the P0 defects found in AUDIT-2026-09-10.md.

Every test here corresponds to a specific numbered finding. They are the
tests that would have caught those bugs before they shipped -- notably
P0-1, which was invisible under ROBOT_BACKEND=mock because the mock LiDAR
puts every point at z=0.0.

Run from the mission-control root:

    python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("core", "mapping", "navigation", "orchestration", "multicam"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from mapping_core import height_bucket, STAIR_WALL_MIN, STAIR_WALL_MAX  # noqa: E402
from astar import astar, build_blocked_grid  # noqa: E402


# ---------------------------------------------------------------------------
# P0-1: a confirmed obstacle must never be re-opened by the stair heuristic
# ---------------------------------------------------------------------------

W = H = 20
WALL_COLUMN = 10


def _wall_map(obstacle_height_m: float):
    floor = [0] * (W * H)
    walls = [0] * (W * H)
    for gy in range(H):
        floor[gy * W + WALL_COLUMN] = 100
        walls[gy * W + WALL_COLUMN] = height_bucket(obstacle_height_m)
    return floor, walls


@pytest.mark.parametrize("height_m", [0.0, 0.2, 0.5, 0.75, 1.0])
def test_astar_never_plans_through_a_confirmed_obstacle(height_m):
    """Obstacles in the 0..1.0m band land inside the stair bucket range.

    Before the fix, build_blocked_grid unconditionally cleared those cells,
    so A* routed straight through walls, tables and human legs.
    """
    floor, walls = _wall_map(height_m)
    blocked = build_blocked_grid(floor, walls, W, H, robot_radius_cells=2,
                                 stair_wall_min=STAIR_WALL_MIN, stair_wall_max=STAIR_WALL_MAX)

    assert blocked[5 * W + WALL_COLUMN] is True, "confirmed obstacle must stay blocked"

    path = astar(W, H, blocked, (2, 10), (18, 10))
    if path is not None:
        assert WALL_COLUMN not in [gx for gx, _ in path], "path crossed the wall"


def test_stair_heuristic_still_clears_inflation_but_not_the_obstacle():
    """A stair cell may shed inherited inflation, never its own occupancy."""
    floor = [0] * (W * H)
    walls = [0] * (W * H)
    floor[5 * W + 5] = 100                      # a plain obstacle
    walls[5 * W + 8] = height_bucket(0.4)       # a nearby "stair" cell, free floor

    blocked = build_blocked_grid(floor, walls, W, H, robot_radius_cells=3,
                                 stair_wall_min=STAIR_WALL_MIN, stair_wall_max=STAIR_WALL_MAX)
    assert blocked[5 * W + 5] is True, "the obstacle itself stays blocked"
    assert blocked[5 * W + 8] is False, "a free stair cell is not sealed off by inflation"


def test_disabled_stair_heuristic_blocks_everything_occupied():
    floor, walls = _wall_map(0.5)
    blocked = build_blocked_grid(floor, walls, W, H, robot_radius_cells=2)
    assert astar(W, H, blocked, (2, 10), (18, 10)) is None


# ---------------------------------------------------------------------------
# P0-3: the live LiDAR response is a bare list, not {"points": [...]}
# ---------------------------------------------------------------------------

def test_live_client_parses_the_bridge_bare_list_format(monkeypatch):
    import live_client

    class FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    # This is exactly what docker/webrtc_bridge/bridge.py returns.
    monkeypatch.setattr(live_client.requests, "get",
                        lambda *a, **k: FakeResp([[1.0, 2.0, 0.3], [1.1, 2.1, 0.35]]))
    client = live_client.LiveRobotClient.__new__(live_client.LiveRobotClient)
    pts = live_client.LiveRobotClient.get_lidar_points(client)
    assert pts == [(1.0, 2.0, 0.3), (1.1, 2.1, 0.35)]

    monkeypatch.setattr(live_client.requests, "get",
                        lambda *a, **k: FakeResp({"points": [{"x": 1.0, "y": 2.0, "z": 0.3}]}))
    assert live_client.LiveRobotClient.get_lidar_points(client) == [(1.0, 2.0, 0.3)]


# ---------------------------------------------------------------------------
# P0-2: telemetry must be read from the keys the bridge actually returns
# ---------------------------------------------------------------------------

BRIDGE_STATE = {
    "sportmodestate": {"position": [1.5, -2.25, 0.31], "imu_state": {"rpy": [0.01, 0.02, 1.57]}},
    "lowstate": {"power_v": 28.4, "power_a": 1.9,
                  "bms_state": {"soc": 73},
                  "imu_state": {"rpy": [0.01, 0.02, 1.55], "accelerometer": [0.0, 0.0, 9.79]}},
    "wireless_controller": {},
}


def _live_client_with_state(monkeypatch, payload):
    import live_client

    client = live_client.LiveRobotClient.__new__(live_client.LiveRobotClient)
    client._last_ok_t = 0.0
    client._last_error = None
    monkeypatch.setattr(live_client.LiveRobotClient, "_state", lambda self: payload)
    return client


def test_live_pose_comes_from_sportmodestate(monkeypatch):
    import live_client

    c = _live_client_with_state(monkeypatch, BRIDGE_STATE)
    pose = live_client.LiveRobotClient.get_pose(c)
    assert (round(pose.x, 2), round(pose.y, 2)) == (1.5, -2.25)
    # yaw must come from SportModeState's OWN imu_state, in sync with position
    assert round(pose.yaw, 2) == 1.57


def test_live_battery_is_not_permanently_zero(monkeypatch):
    import live_client

    c = _live_client_with_state(monkeypatch, BRIDGE_STATE)
    batt = live_client.LiveRobotClient.get_battery(c)
    assert batt.percent == 73
    assert batt.voltage == 28.4


def test_live_link_reports_unhealthy_before_any_successful_poll():
    import live_client

    c = live_client.LiveRobotClient.__new__(live_client.LiveRobotClient)
    c._last_ok_t = 0.0
    assert c.link_age_s() == float("inf")
    assert c.is_link_healthy() is False


# ---------------------------------------------------------------------------
# P0-5: velocity commands are clamped and NaN-safe
# ---------------------------------------------------------------------------

def test_velocity_clamping():
    from live_client import _clamp

    assert _clamp(50.0, 0.8) == 0.8
    assert _clamp(-50.0, 0.8) == -0.8
    assert _clamp(0.3, 0.8) == 0.3
    assert _clamp(float("nan"), 0.8) == 0.0


def test_move_cmd_schema_rejects_out_of_range(monkeypatch):
    monkeypatch.setenv("MC_API_TOKEN", "test-token")
    import importlib

    import service
    importlib.reload(service)

    from pydantic import ValidationError

    service.MoveCmd(vx=0.5, vy=0.0, vyaw=0.2)  # fine
    with pytest.raises(ValidationError):
        service.MoveCmd(vx=50.0)
    with pytest.raises(ValidationError):
        service.MoveCmd(vx=float("inf"))


# ---------------------------------------------------------------------------
# P0-8: call_api must not be usable as an SSRF pivot
# ---------------------------------------------------------------------------

def test_call_api_blocks_internal_and_non_http_targets():
    from task_engine import StepError, validate_outbound_url

    for bad in ("file:///etc/passwd", "gopher://x/", "http://127.0.0.1:9101/arm",
                "http://localhost/", "http://169.254.169.254/latest/meta-data/"):
        with pytest.raises(StepError):
            validate_outbound_url(bad)


# ---------------------------------------------------------------------------
# P0-9: one robot client per camera source, not one per frame
# ---------------------------------------------------------------------------

def test_camera_source_does_not_leak_a_thread_per_frame(monkeypatch):
    monkeypatch.delenv("ROBOT_CLIENT_MODE", raising=False)
    monkeypatch.setenv("ROBOT_BACKEND", "mock")

    from camera_source import RobotClientCameraSource

    cam = RobotClientCameraSource()
    before = threading.active_count()
    for _ in range(15):
        cam.grab_jpeg()
    after = threading.active_count()
    assert after - before <= 1, f"leaked {after - before} threads over 15 frames"


# ---------------------------------------------------------------------------
# P1-1: the orchestration -> sensors paths must match what sensors mounts
# ---------------------------------------------------------------------------

def test_sensor_step_paths_match_the_sensors_service():
    import re

    engine_src = open(os.path.join(ROOT, "orchestration", "task_engine.py"), encoding="utf-8").read()
    sensors_src = open(os.path.join(ROOT, "sensors", "app.py"), encoding="utf-8").read()

    called = set(re.findall(r'"(/sensors?/[a-z_]+)"', engine_src))
    mounted = set(re.findall(r'@app\.post\("(/sensors?/[a-z_]+)"\)', sensors_src))
    assert called, "no sensor endpoints found in task_engine"
    assert called <= mounted, f"task_engine calls endpoints sensors does not mount: {called - mounted}"
