"""Unified robot client interface.

Every other mission-control pillar talks to the robot only through this
interface (never directly to DDS/WebRTC) so pillars can be developed and
tested against `MockRobotClient` without a physical Go2, and swapped to
`LiveRobotClient` with a single env var.

    ROBOT_BACKEND=mock|live   (default: mock)

Reuses (does not reinvent) the connection patterns already proven in the
main repo:
  - DDS SportClient connection: docker/web_dashboard/app.py:_init_sdk()
  - WebRTC camera/LiDAR/telemetry: docker/webrtc_bridge/bridge.py
"""
from __future__ import annotations

import abc
import os
from typing import Optional

from schema import Pose, Battery, ImuSample


class RobotClient(abc.ABC):
    @abc.abstractmethod
    def get_pose(self) -> Pose: ...

    @abc.abstractmethod
    def get_battery(self) -> Battery: ...

    @abc.abstractmethod
    def get_imu(self) -> ImuSample: ...

    @abc.abstractmethod
    def get_camera_frame(self, cam_id: str = "front") -> bytes:
        """Return one JPEG frame as bytes."""

    @abc.abstractmethod
    def get_lidar_points(self) -> list[tuple[float, float, float]]:
        """Return the latest LiDAR point cloud as a list of (x, y, z) in the robot frame."""

    @abc.abstractmethod
    def move(self, vx: float, vy: float, vyaw: float) -> None:
        """Velocity command, same semantics as the official SDK's SportClient.Move()."""

    @abc.abstractmethod
    def stop(self) -> None: ...

    @abc.abstractmethod
    def is_armed(self) -> bool: ...

    @abc.abstractmethod
    def set_armed(self, value: bool) -> None: ...


def get_robot_client() -> RobotClient:
    """Factory used by every pillar.

    ROBOT_CLIENT_MODE=remote (docker-compose default for every pillar
    except `core` itself) -- talk to the `core` service's HTTP API so all
    containers share one robot state instead of each drifting its own
    independent mock. ROBOT_CLIENT_MODE=local (default, e.g. standalone
    `python app.py` dev/testing as documented in each pillar's README) --
    instantiate Mock/LiveRobotClient directly in this process.
    """
    mode = os.environ.get("ROBOT_CLIENT_MODE", "local").lower()
    if mode == "remote":
        from remote_client import RemoteRobotClient
        return RemoteRobotClient()

    backend = os.environ.get("ROBOT_BACKEND", "mock").lower()
    if backend == "live":
        from live_client import LiveRobotClient
        return LiveRobotClient()
    from mock_client import MockRobotClient
    return MockRobotClient()
