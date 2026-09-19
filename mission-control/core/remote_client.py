"""RobotClient implementation that proxies to the `core` service's HTTP API.

Used by every pillar EXCEPT `core` itself when running under
docker-compose (ROBOT_CLIENT_MODE=remote), so all containers observe and
command the same single robot state instead of each spinning up its own
independent mock. See `core/service.py` for the server side.

Every call is wrapped: a `core` outage must not take a pillar down, and
`is_armed()` fails closed (False) so a lost connection can never be read as
permission to keep driving.
"""
from __future__ import annotations

import base64
import os
import threading

import requests

from robot_client import RobotClient
from schema import Pose, Battery, ImuSample

CORE_URL = os.environ.get("CORE_URL", "http://core:9101")
API_TOKEN = os.environ.get("MC_API_TOKEN", "")

# /state is polled by several pillars at ~10 Hz; without this every control
# tick would cost three separate round trips to core.
STATE_CACHE_S = float(os.environ.get("CORE_STATE_CACHE_S", "0.05"))


class CoreUnavailable(RuntimeError):
    pass


class RemoteRobotClient(RobotClient):
    def __init__(self):
        self._timeout = float(os.environ.get("CORE_HTTP_TIMEOUT", "3.0"))
        self._session = requests.Session()
        if API_TOKEN:
            self._session.headers["X-MC-Token"] = API_TOKEN
        self._lock = threading.Lock()
        self._state_cache: dict | None = None
        self._state_cache_t = 0.0

    # -- plumbing ------------------------------------------------------

    def _get(self, path: str, **kwargs) -> dict:
        try:
            r = self._session.get(f"{CORE_URL}{path}", timeout=self._timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise CoreUnavailable(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, **kwargs) -> dict:
        try:
            r = self._session.post(f"{CORE_URL}{path}", timeout=self._timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise CoreUnavailable(f"POST {path} failed: {exc}") from exc

    def _state(self) -> dict:
        import time

        with self._lock:
            if self._state_cache is not None and (time.time() - self._state_cache_t) < STATE_CACHE_S:
                return self._state_cache
        s = self._get("/state")
        with self._lock:
            self._state_cache = s
            self._state_cache_t = time.time()
        return s

    # -- state readers -------------------------------------------------

    def get_pose(self) -> Pose:
        return Pose(**self._state()["pose"])

    def get_battery(self) -> Battery:
        return Battery(**self._state()["battery"])

    def get_imu(self) -> ImuSample:
        return ImuSample(**self._state()["imu"])

    def get_camera_frame(self, cam_id: str = "front") -> bytes:
        r = self._get("/camera_frame", params={"cam_id": cam_id})
        return base64.b64decode(r["jpeg_b64"])

    def get_lidar_points(self) -> list[tuple[float, float, float]]:
        r = self._get("/lidar_points")
        return [(p["x"], p["y"], p["z"]) for p in r["points"]]

    # -- commands ------------------------------------------------------

    def move(self, vx: float, vy: float, vyaw: float) -> None:
        self._post("/move", json={"vx": vx, "vy": vy, "vyaw": vyaw})

    def stop(self) -> None:
        try:
            self._post("/stop")
        except CoreUnavailable:
            # Best effort: if core is unreachable it can no longer be
            # commanded at all, and its own watchdog is what stops the robot.
            pass

    def is_armed(self) -> bool:
        try:
            return bool(self._get("/armed")["armed"])
        except CoreUnavailable:
            # Fail closed: a lost link must never read as "cleared to drive".
            return False

    def set_armed(self, value: bool) -> None:
        self._post("/arm" if value else "/disarm")
