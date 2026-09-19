"""Live robot backend.

Talks to the two services that already exist and are proven to work in the
main NERO_GO2 repo, instead of re-implementing DDS/WebRTC from scratch:

  - `docker/webrtc_bridge` (HTTP, default port 8000 on the Jetson):
    /state (telemetry+pose), /camera.jpg, /lidar (voxel point cloud)
  - The native `unitree_sdk2py` SportClient for movement, as wired up in
    `docker/web_dashboard/app.py::_init_sdk()` -- imported lazily below so
    this module still imports cleanly on a dev machine that doesn't have
    `unitree_sdk2py`/CycloneDDS installed (mission-control is developed
    off-robot; this class is only ever instantiated on the Jetson itself,
    or against a robot reachable over Tailscale).

Configure via env vars:
  WEBRTC_BRIDGE_URL   default http://192.168.123.18:8000
  DDS_NETWORK_IFACE   default eth10

Telemetry field names follow `docker/web_dashboard/app.py`, which is the
only parsing in this project verified against a live robot. See
AUDIT-2026-09-10.md P0-2: the previous field names here were invented and
matched nothing the bridge actually returns.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

from robot_client import RobotClient
from schema import Pose, Battery, ImuSample

BRIDGE_URL = os.environ.get("WEBRTC_BRIDGE_URL", "http://192.168.123.18:8000")
DDS_IFACE = os.environ.get("DDS_NETWORK_IFACE", "eth10")

MAX_VX = float(os.environ.get("MAX_VX", "0.8"))
MAX_VY = float(os.environ.get("MAX_VY", "0.4"))
MAX_VYAW = float(os.environ.get("MAX_VYAW", "1.0"))

LINK_MAX_AGE_S = float(os.environ.get("LINK_MAX_AGE_S", "1.5"))

# Hard, source-level movement lock. With this set the SportClient is never
# initialised and every move() raises, so no code path -- API, pillar or
# bug -- can command the robot. Used when the console is attached purely
# for observation.
READONLY = os.environ.get("ROBOT_READONLY", "0") == "1"


def _clamp(v: float, limit: float) -> float:
    if v != v:  # NaN
        return 0.0
    return max(-limit, min(limit, v))


class LiveRobotClient(RobotClient):
    def __init__(self):
        self._armed = False
        self._sport_client = None
        self._last_ok_t = 0.0
        self._last_error: Optional[str] = None
        self._init_sdk()

    def _init_sdk(self):
        if READONLY:
            print("[live_client] ROBOT_READONLY=1 -- SportClient NOT initialised, "
                  "movement is refused at the source.")
            return
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.go2.sport.sport_client import SportClient

            ChannelFactoryInitialize(0, DDS_IFACE)
            client = SportClient()
            client.SetTimeout(5.0)
            client.Init()
            self._sport_client = client
        except Exception as exc:  # pragma: no cover - only reachable on the Jetson
            print(f"[live_client] DDS SportClient unavailable ({exc}) -- "
                  f"movement commands will be REFUSED (not silently dropped).")
            self._sport_client = None

    # -- telemetry link ------------------------------------------------

    def _state(self) -> dict:
        try:
            r = requests.get(f"{BRIDGE_URL}/state", timeout=2.0)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            self._last_error = str(exc)
            return {}
        self._last_ok_t = time.time()
        self._last_error = None
        return data if isinstance(data, dict) else {}

    def link_age_s(self) -> float:
        """Seconds since the last valid telemetry response, inf if never."""
        return (time.time() - self._last_ok_t) if self._last_ok_t else float("inf")

    def is_link_healthy(self, max_age_s: float = LINK_MAX_AGE_S) -> bool:
        return self.link_age_s() <= max_age_s

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # -- state readers -------------------------------------------------

    def has_pose(self) -> bool:
        """sportmodestate only publishes while sport mode is active. Until it
        does there is no position at all -- callers must show it as absent
        rather than as the origin."""
        sms = self._state().get("sportmodestate")
        return bool(sms) and sms.get("position") is not None

    def get_pose(self) -> Pose:
        sms = self._state().get("sportmodestate") or {}
        pos = sms.get("position") or [0.0, 0.0, 0.0]
        # The yaw MUST come from SportModeState's own imu_state, i.e. the same
        # DDS message as `position`. LowState carries a separate, asynchronous
        # yaw; pairing it with this position is what produced the
        # motion-dependent map skew documented on 2026-09-05.
        rpy = (sms.get("imu_state") or {}).get("rpy") or [0.0, 0.0, 0.0]
        return Pose(x=float(pos[0]), y=float(pos[1]), z=float(pos[2]), yaw=float(rpy[2]))

    def get_battery(self) -> Battery:
        low = self._state().get("lowstate") or {}
        bms = low.get("bms_state") or low.get("bms") or {}
        return Battery(
            voltage=float(low.get("power_v", 0.0)),
            current=float(low.get("power_a", 0.0)),
            percent=float(bms.get("soc", 0.0)),
        )

    def get_imu(self) -> ImuSample:
        imu = (self._state().get("lowstate") or {}).get("imu_state") or {}
        rpy = imu.get("rpy") or [0.0, 0.0, 0.0]
        # Verified against the live robot 2026-09-11: rt/lf/lowstate carries
        # imu_state.rpy but no accelerometer, so accel_z stays nominal.
        acc = imu.get("accelerometer") or [0.0, 0.0, 9.81]
        return ImuSample(roll=float(rpy[0]), pitch=float(rpy[1]), yaw=float(rpy[2]),
                          accel_z=float(acc[2]))

    def get_camera_frame(self, cam_id: str = "front") -> bytes:
        r = requests.get(f"{BRIDGE_URL}/camera.jpg", timeout=3.0)
        r.raise_for_status()
        return r.content

    def get_lidar_points(self) -> list[tuple[float, float, float]]:
        r = requests.get(f"{BRIDGE_URL}/lidar", timeout=3.0)
        r.raise_for_status()
        data = r.json()
        # The bridge returns a bare [[x,y,z], ...] list (bridge.py:
        # jsonify(points.tolist())). The dict form is tolerated only in case
        # a future version wraps it.
        if isinstance(data, dict):
            data = data.get("points", [])
        out: list[tuple[float, float, float]] = []
        for p in data:
            if isinstance(p, dict):
                out.append((float(p["x"]), float(p["y"]), float(p["z"])))
            else:
                out.append((float(p[0]), float(p[1]), float(p[2])))
        return out

    # -- commands ------------------------------------------------------

    def move(self, vx: float, vy: float, vyaw: float) -> None:
        if READONLY:
            raise PermissionError("ROBOT_READONLY=1 -- movement is disabled")
        if self._sport_client is None:
            raise RuntimeError("SportClient unavailable -- movement command NOT delivered")
        if not self._armed:
            raise PermissionError("robot is not armed")
        code = self._sport_client.Move(
            _clamp(vx, MAX_VX), _clamp(vy, MAX_VY), _clamp(vyaw, MAX_VYAW)
        )
        # ELLENŐRIZENDŐ: unitree_sdk2py returns an int status here (0 == OK).
        # Confirm against the official SDK examples on the first live run.
        if isinstance(code, int) and code != 0:
            raise RuntimeError(f"SportClient.Move returned error code {code}")

    def stop(self) -> None:
        if READONLY or self._sport_client is None:
            return
        try:
            self._sport_client.Move(0.0, 0.0, 0.0)
        except Exception as exc:
            print(f"[live_client] stop() failed: {exc}")

    def is_armed(self) -> bool:
        return self._armed

    def set_armed(self, value: bool) -> None:
        if value and READONLY:
            raise PermissionError("ROBOT_READONLY=1 -- arming is disabled")
        self._armed = value
        if not value:
            self.stop()
