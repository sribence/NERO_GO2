"""mission-control: navigation pillar (port 9103).

Click-to-goal path planning: fetches the current dual-layer map from the
mapping pillar, runs A* over the floor layer (inflated by a robot-radius
safety margin), then drives the robot along the resulting waypoints in a
background thread. /goto returns immediately with a nav_id; poll
/nav_status for progress.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import uuid
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
import uvicorn

from robot_client import get_robot_client

from astar import (
    astar,
    build_blocked_grid,
    grid_to_world,
    is_stair_cell,
    nearest_free_cell,
    world_to_grid,
)

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

PILLAR = "navigation"
PORT = 9103

MAPPING_URL = os.environ.get("MAPPING_URL", "http://localhost:9102")
ROBOT_RADIUS_M = float(os.environ.get("ROBOT_RADIUS_M", "0.25"))

FORWARD_SPEED = float(os.environ.get("NAV_FORWARD_SPEED", "0.4"))
STAIR_SPEED = float(os.environ.get("NAV_STAIR_SPEED", "0.12"))
YAW_KP = float(os.environ.get("NAV_YAW_KP", "1.4"))
WAYPOINT_TOL_M = float(os.environ.get("NAV_WAYPOINT_TOL_M", "0.12"))
TICK_S = float(os.environ.get("NAV_TICK_S", "0.1"))
STUCK_WARN_S = float(os.environ.get("NAV_STUCK_WARN_S", "10.0"))
STUCK_FAIL_S = float(os.environ.get("NAV_STUCK_FAIL_S", "30.0"))

# Height-based stair detection is OFF by default: the 30..120 bucket band
# covers every obstacle below ~1m, so enabling it makes A* plan through
# walls (AUDIT-2026-09-10.md, P0-1). Only turn on once validated on the
# real robot, and with a band that starts above furniture height.
NAV_STAIRS_ENABLED = os.environ.get("NAV_STAIRS_ENABLED", "0") == "1"
STAIR_WALL_MIN = int(os.environ.get("NAV_STAIR_WALL_MIN", "150"))
STAIR_WALL_MAX = int(os.environ.get("NAV_STAIR_WALL_MAX", "200"))

# Direct, map-independent emergency brake while driving.
SAFETY_STOP_M = float(os.environ.get("NAV_SAFETY_STOP_M", "0.45"))
SAFETY_CONE_RAD = float(os.environ.get("NAV_SAFETY_CONE_RAD", "0.6"))
SAFETY_Z_MIN = float(os.environ.get("NAV_SAFETY_Z_MIN", "-0.3"))
SAFETY_Z_MAX = float(os.environ.get("NAV_SAFETY_Z_MAX", "0.8"))

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_PATH = os.path.join(LOG_DIR, "events.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)
_log_lock = threading.Lock()


def log_event(level: str, msg: str, **extra) -> None:
    rec = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    line = json.dumps(rec)
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line, flush=True)


def _wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _obstacle_ahead(robot, pose) -> tuple[bool, str]:
    """Map-independent emergency brake.

    The planner sees only the map snapshot taken when /goto was issued, so
    anything that arrives afterwards -- a person stepping in, a moved chair
    -- is invisible to it. This checks the live scan for a return inside
    SAFETY_STOP_M within a cone around the heading, every control tick.
    """
    try:
        pts = robot.get_lidar_points()
    except Exception as exc:
        return True, f"lidar unavailable: {exc}"
    for px, py, pz in pts:
        if not (SAFETY_Z_MIN <= pz <= SAFETY_Z_MAX):
            continue
        dx, dy = px - pose.x, py - pose.y
        d = math.hypot(dx, dy)
        if d > SAFETY_STOP_M or d < 1e-3:
            continue
        if abs(_wrap_angle(math.atan2(dy, dx) - pose.yaw)) <= SAFETY_CONE_RAD:
            return True, f"obstacle {d:.2f}m ahead"
    return False, ""


class NavService:
    def __init__(self):
        self.robot = get_robot_client()
        self._redis = None
        if redis is not None:
            try:
                self._redis = redis.Redis(
                    host=os.environ.get("REDIS_HOST", "redis"), port=6379, decode_responses=True,
                    socket_connect_timeout=1.0,
                )
                self._redis.ping()
            except Exception as exc:
                log_event("warn", "redis unavailable, anomaly publishing disabled", error=str(exc))
                self._redis = None

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self.nav_id: Optional[str] = None
        self.state = "idle"   # idle | planning | moving | blocked | done | failed | cancelled
        self.goal: Optional[tuple[float, float]] = None
        self.remaining_path: list[tuple[float, float]] = []
        self.error: Optional[str] = None

    def _publish_anomaly(self, msg: str, **extra) -> None:
        if self._redis is None:
            return
        try:
            self._redis.publish("mc.core.anomaly", json.dumps({
                "t": time.time(), "pillar": PILLAR, "msg": msg, **extra,
            }))
        except Exception as exc:
            log_event("warn", "anomaly publish failed", error=str(exc))

    def status(self) -> dict:
        return {
            "nav_id": self.nav_id,
            "state": self.state,
            "goal": {"x": self.goal[0], "y": self.goal[1]} if self.goal else None,
            "remaining_path": [{"x": x, "y": y} for x, y in self.remaining_path],
            "error": self.error,
        }

    def goto(self, x: float, y: float) -> str:
        with self._lock:
            if not self.robot.is_armed():
                raise PermissionError("robot not armed")
            if self._thread is not None and self._thread.is_alive():
                self._cancel_event.set()
                self._thread.join(timeout=5.0)
            self._cancel_event.clear()
            self.nav_id = uuid.uuid4().hex[:12]
            self.state = "planning"
            self.goal = (x, y)
            self.remaining_path = []
            self.error = None
            nav_id = self.nav_id
            self._thread = threading.Thread(target=self._run, args=(nav_id, x, y), daemon=True)
            self._thread.start()
            return nav_id

    def cancel(self) -> None:
        self._cancel_event.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)
        self.robot.stop()
        if self.state in ("planning", "moving", "blocked"):
            self.state = "cancelled"
        log_event("info", "navigation cancelled", nav_id=self.nav_id)

    # -- background worker ---------------------------------------------
    def _run(self, nav_id: str, goal_x: float, goal_y: float) -> None:
        try:
            resp = requests.get(f"{MAPPING_URL}/map", timeout=5.0)
            resp.raise_for_status()
            m = resp.json()
        except Exception as exc:
            self._fail(nav_id, f"could not fetch map from mapping ({MAPPING_URL}): {exc}")
            return

        width, height = m["width"], m["height"]
        resolution, origin_x, origin_y = m["resolution"], m["origin_x"], m["origin_y"]
        floor, walls = m["floor"], m["walls"]

        radius_cells = max(0, round(ROBOT_RADIUS_M / resolution))
        blocked = build_blocked_grid(
            floor, walls, width, height, radius_cells,
            stair_wall_min=STAIR_WALL_MIN if NAV_STAIRS_ENABLED else None,
            stair_wall_max=STAIR_WALL_MAX if NAV_STAIRS_ENABLED else None,
        )

        pose = self.robot.get_pose()
        start_cell = world_to_grid(pose.x, pose.y, origin_x, origin_y, resolution)
        goal_cell = world_to_grid(goal_x, goal_y, origin_x, origin_y, resolution)

        start_cell = nearest_free_cell(blocked, width, height, start_cell)
        goal_cell = nearest_free_cell(blocked, width, height, goal_cell) if goal_cell is not None else None
        if start_cell is None or goal_cell is None:
            self._fail(nav_id, "start or goal has no reachable free cell nearby")
            return

        path_cells = astar(width, height, blocked, start_cell, goal_cell)
        if path_cells is None:
            self._fail(nav_id, "no path found to goal")
            return

        waypoints = [grid_to_world(gx, gy, origin_x, origin_y, resolution) for gx, gy in path_cells]
        if self.nav_id != nav_id or self._cancel_event.is_set():
            return
        self.remaining_path = list(waypoints)
        self.state = "moving"
        log_event("info", "path planned", nav_id=nav_id, waypoints=len(waypoints))

        ok = self._drive(nav_id, waypoints, walls, width, origin_x, origin_y, resolution)
        if self.nav_id != nav_id:
            return  # superseded by a newer /goto
        if self._cancel_event.is_set():
            self.state = "cancelled"
            return
        if ok:
            self.state = "done"
            self.remaining_path = []
            log_event("info", "navigation done", nav_id=nav_id)
        # on failure, _drive already set self.state/self.error

    def _drive(self, nav_id: str, waypoints: list[tuple[float, float]], walls: list[int],
               width: int, origin_x: float, origin_y: float, resolution: float) -> bool:
        height = len(walls) // width
        last_progress_t = time.time()
        best_remaining = None
        warned_stuck = False

        for i, (wx, wy) in enumerate(waypoints):
            while True:
                if self._cancel_event.is_set() or self.nav_id != nav_id:
                    return False
                if not self.robot.is_armed():
                    self._fail(nav_id, "robot disarmed mid-navigation")
                    return False

                pose = self.robot.get_pose()
                dx, dy = wx - pose.x, wy - pose.y
                dist = math.hypot(dx, dy)

                total_remaining = dist + sum(
                    math.hypot(waypoints[j + 1][0] - waypoints[j][0], waypoints[j + 1][1] - waypoints[j][1])
                    for j in range(i, len(waypoints) - 1)
                )
                if best_remaining is None or total_remaining < best_remaining - 0.02:
                    best_remaining = total_remaining
                    last_progress_t = time.time()
                    if warned_stuck:
                        warned_stuck = False
                        self.state = "moving"

                stuck_for = time.time() - last_progress_t
                if stuck_for > STUCK_FAIL_S:
                    self._fail(nav_id, f"no progress for {stuck_for:.0f}s, giving up")
                    return False
                if stuck_for > STUCK_WARN_S and not warned_stuck:
                    warned_stuck = True
                    self.state = "blocked"
                    self._publish_anomaly("navigation stuck: no progress for >10s while moving",
                                           nav_id=nav_id, x=pose.x, y=pose.y)
                    log_event("warn", "navigation appears stuck", nav_id=nav_id, stuck_for=stuck_for)

                if dist < WAYPOINT_TOL_M:
                    self.remaining_path = list(waypoints[i + 1:])
                    break

                target_yaw = math.atan2(dy, dx)
                yaw_err = _wrap_angle(target_yaw - pose.yaw)

                gx, gy = world_to_grid(pose.x, pose.y, origin_x, origin_y, resolution)
                on_stairs = (NAV_STAIRS_ENABLED and 0 <= gx < width and 0 <= gy < height and
                             is_stair_cell(walls, width, gx, gy, STAIR_WALL_MIN, STAIR_WALL_MAX))
                speed = STAIR_SPEED if on_stairs else FORWARD_SPEED

                hit, why = _obstacle_ahead(self.robot, pose)
                if hit:
                    self.robot.stop()
                    if self.state != "blocked":
                        self.state = "blocked"
                        self._publish_anomaly("safety brake engaged", nav_id=nav_id,
                                               reason=why, x=pose.x, y=pose.y)
                        log_event("warn", "safety brake engaged", nav_id=nav_id, reason=why)
                    time.sleep(TICK_S)
                    continue

                vyaw = max(-1.0, min(1.0, YAW_KP * yaw_err))
                vx = speed * max(0.15, 1.0 - abs(yaw_err) / math.pi)
                try:
                    self.robot.move(vx, 0.0, vyaw)
                except Exception as exc:
                    self._fail(nav_id, f"move command refused: {exc}")
                    return False
                time.sleep(TICK_S)

        self.robot.stop()
        return True

    def _fail(self, nav_id: str, msg: str) -> None:
        if self.nav_id == nav_id:
            self.state = "failed"
            self.error = msg
        self.robot.stop()
        log_event("error", msg, nav_id=nav_id)


svc = NavService()
app = FastAPI(title="mission-control: navigation")


class GotoBody(BaseModel):
    x: float
    y: float


@app.post("/goto", status_code=202)
def goto(body: GotoBody):
    try:
        nav_id = svc.goto(body.x, body.y)
    except PermissionError:
        raise HTTPException(status_code=409, detail="robot is not armed")
    return {"nav_id": nav_id, "state": svc.state}


@app.post("/goto/cancel")
def goto_cancel():
    svc.cancel()
    return svc.status()


@app.get("/nav_status")
def nav_status():
    return svc.status()


@app.get("/health")
def health():
    return {"ok": True, "pillar": PILLAR, "state": svc.state}


if os.environ.get("MC_ENABLE_DEBUG_ENDPOINTS") == "1":
    # Only mounted when explicitly enabled. These bypass core's shared
    # arm state entirely, so leaving them always-on means anyone who can
    # reach the port can arm the robot (AUDIT-2026-09-10.md, P0-7).

    @app.post("/_debug/arm")
    def debug_arm():
        svc.robot.set_armed(True)
        return {"armed": True}

    @app.post("/_debug/disarm")
    def debug_disarm():
        svc.robot.set_armed(False)
        return {"armed": False}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
