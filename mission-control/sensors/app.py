"""mission-control: sensors pillar (port 9105).

On-demand sensor command endpoints -- single snapshots, not continuous
streams (continuous multi-camera capture lives in the `multicam` pillar).

Endpoints:
    POST /sensor/photo        -- one JPEG frame from robot.get_camera_frame()
    POST /sensor/lidar_scan   -- one dense LiDAR point-cloud snapshot (JSON)
    POST /sensor/thermal      -- 501 stub, no thermal hardware yet (see README.md)

Talks to the robot only through `core/robot_client.py`, per CONVENTIONS.md.
"""
from __future__ import annotations

import abc
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from robot_client import get_robot_client

PILLAR = "sensors"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "events.jsonl")

os.makedirs(CAPTURES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

app = FastAPI(title="mission-control: sensors")
app.mount("/captures", StaticFiles(directory=CAPTURES_DIR), name="captures")

robot = get_robot_client()


def log_event(level: str, msg: str, **extra) -> None:
    """Append one JSONL line per CONVENTIONS.md log format."""
    record = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        # Logging must never take the service down.
        pass


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime()) + f"_{int((time.time() % 1) * 1000):03d}"


# ---------------------------------------------------------------------------
# /sensor/photo
# ---------------------------------------------------------------------------

@app.post("/sensor/photo")
def sensor_photo(cam_id: str = "front"):
    ts = _timestamp()
    filename = f"photo_{ts}.jpg"
    path = os.path.join(CAPTURES_DIR, filename)
    try:
        frame = robot.get_camera_frame(cam_id)
        with open(path, "wb") as f:
            f.write(frame)
    except Exception as exc:
        log_event("error", "photo capture failed", cam_id=cam_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"photo capture failed: {exc}") from exc

    log_event("info", "photo captured", cam_id=cam_id, path=path, bytes=len(frame))
    return {"path": path, "url": f"/captures/{filename}"}


# ---------------------------------------------------------------------------
# /sensor/lidar_scan
# ---------------------------------------------------------------------------

@app.post("/sensor/lidar_scan")
def sensor_lidar_scan():
    ts = _timestamp()
    filename = f"lidar_{ts}.json"
    path = os.path.join(CAPTURES_DIR, filename)
    try:
        points = robot.get_lidar_points()
        points_list = [[float(x), float(y), float(z)] for (x, y, z) in points]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(points_list, f)
    except Exception as exc:
        log_event("error", "lidar scan failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"lidar scan failed: {exc}") from exc

    log_event("info", "lidar scan captured", path=path, point_count=len(points_list))
    return {"path": path, "point_count": len(points_list)}


# ---------------------------------------------------------------------------
# /sensor/thermal -- honest stub, no hardware exists yet
# ---------------------------------------------------------------------------

class ThermalCapture(abc.ABC):
    """Abstraction for a thermal-camera capture backend.

    Deferred in the project plan: no USB thermal camera is wired up yet.
    When one is added, implement a concrete subclass (e.g. a FLIR/Seek USB
    capture backed by its SDK or a v4l2/OpenCV grab of the thermal stream)
    and swap it in below -- the /sensor/thermal endpoint itself does not
    need to change.
    """

    @abc.abstractmethod
    def is_configured(self) -> bool:
        ...

    @abc.abstractmethod
    def capture(self) -> bytes:
        """Return one thermal frame (e.g. as a radiometric or false-color JPEG)."""


class NotConfiguredThermalCapture(ThermalCapture):
    """Placeholder backend: always reports unconfigured, never captures."""

    def is_configured(self) -> bool:
        return False

    def capture(self) -> bytes:
        raise RuntimeError("no thermal hardware configured")


thermal_capture: ThermalCapture = NotConfiguredThermalCapture()


@app.post("/sensor/thermal")
def sensor_thermal():
    if not thermal_capture.is_configured():
        log_event("warn", "thermal capture requested but no hardware configured")
        return JSONResponse(
            status_code=501,
            content={
                "error": "no thermal hardware configured yet",
                "note": (
                    "Thermal camera support is explicitly deferred -- no USB thermal "
                    "cam is wired up on this robot yet. To add it: implement a new "
                    "ThermalCapture subclass in sensors/app.py (e.g. backed by the "
                    "vendor SDK or a v4l2/OpenCV grab), swap it into `thermal_capture`, "
                    "and this endpoint will start returning real frames without any "
                    "other changes."
                ),
            },
        )
    # Unreachable until a real ThermalCapture backend is plugged in above.
    ts = _timestamp()
    filename = f"thermal_{ts}.jpg"
    path = os.path.join(CAPTURES_DIR, filename)
    frame = thermal_capture.capture()
    with open(path, "wb") as f:
        f.write(frame)
    log_event("info", "thermal captured", path=path, bytes=len(frame))
    return {"path": path, "url": f"/captures/{filename}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9105)
