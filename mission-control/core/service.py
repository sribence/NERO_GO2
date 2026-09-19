"""HTTP-exposed robot client (port 9101).

This is the single process that actually owns the `RobotClient` (mock or
live) instance for the whole stack. Every other pillar, when running under
`docker-compose` (ROBOT_CLIENT_MODE=remote, the compose default for
non-core services), talks to the robot ONLY through this HTTP API via
`remote_client.RemoteRobotClient` -- never by instantiating its own
Mock/LiveRobotClient. That keeps pose/battery/arm-state consistent across
every container instead of each one drifting its own independent mock
robot. Standalone/local dev (no docker-compose) still defaults to
ROBOT_CLIENT_MODE=local, so a single pillar can be run and curl'd on its
own exactly as each pillar's own README documents.

Safety surface owned by this service (see AUDIT-2026-09-10.md):
  - every velocity command is range-checked before it reaches the robot
  - a watchdog stops the robot if commands stop arriving
  - POST /estop is always reachable, unauthenticated, and idempotent
  - every state-changing endpoint requires MC_API_TOKEN
"""
from __future__ import annotations

import base64
import os
import secrets
import threading
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from robot_client import get_robot_client

# Conservative indoor operator limits. The Go2 sport mode accepts more than
# this; this system deliberately does not offer it.
MAX_VX = float(os.environ.get("MAX_VX", "0.8"))
MAX_VY = float(os.environ.get("MAX_VY", "0.4"))
MAX_VYAW = float(os.environ.get("MAX_VYAW", "1.0"))

# If no new move command arrives within this window the robot is stopped.
# Both driving pillars command at ~10 Hz, so 0.5s is ~5 missed ticks.
COMMAND_TIMEOUT_S = float(os.environ.get("COMMAND_TIMEOUT_S", "0.5"))

API_TOKEN = os.environ.get("MC_API_TOKEN", "")
READONLY = os.environ.get("ROBOT_READONLY", "0") == "1"

app = FastAPI(title="mission-control: core")
robot = get_robot_client()

_cmd_lock = threading.Lock()
_last_cmd_t = 0.0
_watchdog_trips = 0


def require_token(x_mc_token: str = Header(default="")) -> None:
    """Guard for every state-changing endpoint.

    With no token configured the service still starts but refuses all
    writes, so a forgotten configuration fails closed rather than leaving
    arm/move open to anyone who can reach the port.
    """
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="MC_API_TOKEN is not configured")
    if not secrets.compare_digest(x_mc_token, API_TOKEN):
        raise HTTPException(status_code=401, detail="invalid token")


class MoveCmd(BaseModel):
    model_config = {"allow_inf_nan": False}

    vx: float = Field(0.0, ge=-MAX_VX, le=MAX_VX)
    vy: float = Field(0.0, ge=-MAX_VY, le=MAX_VY)
    vyaw: float = Field(0.0, ge=-MAX_VYAW, le=MAX_VYAW)


def _watchdog_loop() -> None:
    global _watchdog_trips, _last_cmd_t
    while True:
        time.sleep(0.1)
        with _cmd_lock:
            last = _last_cmd_t
        if not last or (time.time() - last) <= COMMAND_TIMEOUT_S:
            continue
        with _cmd_lock:
            if _last_cmd_t != last:
                continue
            _last_cmd_t = 0.0
            _watchdog_trips += 1
        try:
            robot.stop()
        except Exception:
            pass


threading.Thread(target=_watchdog_loop, daemon=True, name="core-watchdog").start()


# -- proximity monitor -------------------------------------------------
# CONVENTIONS.md defines `mc.core.proximity_alert` and the audio pillar
# subscribes to it, but nothing ever published: the whole human-proximity
# warning was a phantom feature (AUDIT-2026-09-10.md, P0-12).

PROXIMITY_ALERT_M = float(os.environ.get("PROXIMITY_ALERT_M", "0.8"))
PROXIMITY_Z_MIN = float(os.environ.get("PROXIMITY_Z_MIN", "-0.3"))
PROXIMITY_Z_MAX = float(os.environ.get("PROXIMITY_Z_MAX", "1.2"))
PROXIMITY_PERIOD_S = float(os.environ.get("PROXIMITY_PERIOD_S", "0.5"))

_proximity: dict = {"active": False, "min_distance_m": None, "t": 0.0}


def _proximity_loop() -> None:
    import json
    import math

    r = None
    try:
        import redis as redis_lib

        r = redis_lib.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379,
                            decode_responses=True, socket_connect_timeout=1.0)
        r.ping()
    except Exception:
        r = None  # bus optional; /state still exposes the flag for the UI

    while True:
        time.sleep(PROXIMITY_PERIOD_S)
        try:
            pose = robot.get_pose()
            pts = robot.get_lidar_points()
        except Exception:
            continue
        nearest = None
        for px, py, pz in pts:
            if not (PROXIMITY_Z_MIN <= pz <= PROXIMITY_Z_MAX):
                continue
            d = math.hypot(px - pose.x, py - pose.y)
            if d < 1e-3:
                continue
            if nearest is None or d < nearest:
                nearest = d
        active = nearest is not None and nearest <= PROXIMITY_ALERT_M
        was = _proximity["active"]
        _proximity.update(active=active, min_distance_m=nearest, t=time.time())
        if active and not was and r is not None:
            try:
                r.publish("mc.core.proximity_alert", json.dumps({
                    "t": time.time(), "pillar": "core",
                    "min_distance_m": round(nearest, 3),
                    "threshold_m": PROXIMITY_ALERT_M,
                }))
            except Exception:
                pass


threading.Thread(target=_proximity_loop, daemon=True, name="core-proximity").start()


def _link_health() -> dict:
    """Freshness of the underlying telemetry link, when the backend tracks it.

    Without this a dead connection is indistinguishable from a robot parked
    at the origin with a flat battery, because every field falls back to 0.
    """
    age = getattr(robot, "link_age_s", None)
    if age is None:
        return {"tracked": False, "healthy": True, "age_s": None}
    a = age()
    return {"tracked": True, "healthy": robot.is_link_healthy(), "age_s": None if a == float("inf") else round(a, 3)}


@app.get("/state")
def state():
    # Absent rather than the origin when the robot has no position fix.
    has_pose = getattr(robot, "has_pose", lambda: True)()
    return {
        "readonly": READONLY,
        "pose": robot.get_pose().to_dict() if has_pose else None,
        "battery": robot.get_battery().to_dict(),
        "imu": robot.get_imu().to_dict(),
        "armed": robot.is_armed(),
        "link": _link_health(),
        "proximity": dict(_proximity),
        "watchdog_trips": _watchdog_trips,
        "limits": {"max_vx": MAX_VX, "max_vy": MAX_VY, "max_vyaw": MAX_VYAW},
    }


@app.get("/armed")
def armed():
    return {"armed": robot.is_armed()}


@app.get("/health")
def health():
    return {"ok": True, "pillar": "core", "readonly": READONLY, "link": _link_health()}


@app.post("/arm", dependencies=[Depends(require_token)])
def arm():
    if READONLY:
        raise HTTPException(status_code=403, detail="ROBOT_READONLY=1 -- arming is disabled")
    link = _link_health()
    if link["tracked"] and not link["healthy"]:
        raise HTTPException(status_code=409, detail="refusing to arm: telemetry link is stale")
    robot.set_armed(True)
    return {"armed": True}


@app.post("/disarm", dependencies=[Depends(require_token)])
def disarm():
    robot.set_armed(False)
    return {"armed": False}


@app.post("/estop")
def estop():
    """Emergency stop: stop + disarm, idempotent.

    Deliberately unauthenticated. It can only ever make the robot safer,
    never move it, so requiring a token would add a way to fail to stop a
    moving robot in exchange for preventing a nuisance at worst.
    """
    global _last_cmd_t
    with _cmd_lock:
        _last_cmd_t = 0.0
    errors = []
    for action in (robot.stop, lambda: robot.set_armed(False)):
        try:
            action()
        except Exception as exc:
            errors.append(str(exc))
    return {"estop": True, "armed": robot.is_armed(), "errors": errors}


@app.post("/move", dependencies=[Depends(require_token)])
def move(cmd: MoveCmd):
    global _last_cmd_t
    if READONLY:
        raise HTTPException(status_code=403, detail="ROBOT_READONLY=1 -- movement is disabled")
    if not robot.is_armed():
        raise HTTPException(status_code=409, detail="robot is not armed, command dropped")
    link = _link_health()
    if link["tracked"] and not link["healthy"]:
        raise HTTPException(status_code=409, detail="telemetry link is stale, command dropped")
    try:
        robot.move(cmd.vx, cmd.vy, cmd.vyaw)
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with _cmd_lock:
        _last_cmd_t = time.time()
    return {"ok": True, "armed": True}


@app.post("/stop", dependencies=[Depends(require_token)])
def stop():
    global _last_cmd_t
    with _cmd_lock:
        _last_cmd_t = 0.0
    robot.stop()
    return {"ok": True}


@app.get("/camera_frame")
def camera_frame(cam_id: str = "front"):
    try:
        jpeg = robot.get_camera_frame(cam_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"camera unavailable: {exc}") from exc
    return {"cam_id": cam_id, "jpeg_b64": base64.b64encode(jpeg).decode("ascii")}


@app.get("/lidar_points")
def lidar_points():
    try:
        pts = robot.get_lidar_points()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"lidar unavailable: {exc}") from exc
    return {"points": [{"x": p[0], "y": p[1], "z": p[2]} for p in pts]}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)
