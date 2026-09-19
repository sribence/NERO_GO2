"""Synthetic robot backend — same idea as docker/mock_robot/ in the main repo.

Generates a slow random walk for pose, a slowly draining battery, a
placeholder JPEG frame, and a synthetic circular LiDAR sweep so every
other pillar has something real to render/consume without a physical robot.
"""
from __future__ import annotations

import io
import math
import random
import threading
import time

from robot_client import RobotClient
from schema import Pose, Battery, ImuSample


class MockRobotClient(RobotClient):
    def __init__(self):
        self._lock = threading.Lock()
        self._pose = Pose(x=0.0, y=0.0, z=0.0, yaw=0.0)
        self._battery_pct = 100.0
        self._armed = False
        self._vx = self._vy = self._vyaw = 0.0
        self._start_t = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def _tick_loop(self):
        last = time.time()
        while not self._stop.is_set():
            now = time.time()
            dt = now - last
            last = now
            with self._lock:
                if self._armed:
                    yaw = self._pose.yaw + self._vyaw * dt
                    dx = (self._vx * math.cos(yaw) - self._vy * math.sin(yaw)) * dt
                    dy = (self._vx * math.sin(yaw) + self._vy * math.cos(yaw)) * dt
                    self._pose = Pose(
                        x=self._pose.x + dx,
                        y=self._pose.y + dy,
                        z=0.0,
                        yaw=yaw,
                        level_id=self._pose.level_id,
                    )
                    drain = 0.02 * dt * (1 + abs(self._vx) + abs(self._vyaw))
                    self._battery_pct = max(0.0, self._battery_pct - drain)
            time.sleep(0.05)

    def get_pose(self) -> Pose:
        with self._lock:
            return self._pose

    def get_battery(self) -> Battery:
        with self._lock:
            pct = self._battery_pct
        return Battery(voltage=22.0 + 0.06 * pct, current=0.4 + 0.3 * random.random(), percent=pct)

    def get_imu(self) -> ImuSample:
        t = time.time() - self._start_t
        return ImuSample(
            roll=0.02 * math.sin(t * 1.3),
            pitch=0.02 * math.sin(t * 0.9),
            yaw=self.get_pose().yaw,
            accel_z=9.81 + 0.05 * math.sin(t * 4),
        )

    def get_camera_frame(self, cam_id: str = "front") -> bytes:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # PIL not installed in this environment -- return a tiny static
            # 1x1 JPEG so callers still get valid bytes to write to disk.
            return bytes.fromhex(
                "ffd8ffe000104a46494600010100000100010000ffdb004300030202020"
                "203020202030303030405080505040404050a070706080c0a0c0c0b0a0b"
                "0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141"
                "5140fffc0000b080001000101011100021101031101ffc4001f00000105"
                "0101010101010000000000000000010203040506070809ffda0008010"
                "10100003f00d2cf20ffd9"
            )
        img = Image.new("RGB", (320, 240), (20, 24, 30))
        d = ImageDraw.Draw(img)
        pose = self.get_pose()
        d.text((10, 10), f"MOCK cam={cam_id}", fill=(0, 255, 140))
        d.text((10, 26), f"pose=({pose.x:.2f},{pose.y:.2f},yaw={pose.yaw:.2f})", fill=(0, 200, 255))
        d.text((10, 42), f"t={time.time():.1f}", fill=(180, 180, 180))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def get_lidar_points(self) -> list[tuple[float, float, float]]:
        pose = self.get_pose()
        pts = []
        for i in range(180):
            angle = pose.yaw + (i / 180.0) * 2 * math.pi
            r = 2.0 + 1.5 * abs(math.sin(angle * 3 + time.time() * 0.2))
            pts.append((pose.x + r * math.cos(angle), pose.y + r * math.sin(angle), 0.0))
        return pts

    def move(self, vx: float, vy: float, vyaw: float) -> None:
        with self._lock:
            if not self._armed:
                return
            self._vx, self._vy, self._vyaw = vx, vy, vyaw

    def stop(self) -> None:
        self.move(0.0, 0.0, 0.0)

    def is_armed(self) -> bool:
        return self._armed

    def set_armed(self, value: bool) -> None:
        with self._lock:
            self._armed = value
            if not value:
                self._vx = self._vy = self._vyaw = 0.0
