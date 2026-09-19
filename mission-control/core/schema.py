"""Shared data shapes used by every mission-control pillar.

Kept dependency-free (stdlib only) so every service can import this
without pulling in the whole `core` package's HTTP/DDS clients.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import time


@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    level_id: str = "ground"
    t: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Battery:
    voltage: float = 28.0
    current: float = 0.5
    percent: float = 100.0
    t: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImuSample:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    accel_z: float = 9.81
    t: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)
