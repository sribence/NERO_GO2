"""Fleet pillar — multi-robot mission control backend (port 9111).

Serves per-robot state for every robot in the fleet. Skeleton uses mock
data only; real backends plug in later via ROBOT_BACKEND-style clients
per robot_id (see core/robot_client.py for the single-robot pattern).
"""
from __future__ import annotations

import math
import random
import time
from typing import Literal

from fastapi import FastAPI, HTTPException
import uvicorn

app = FastAPI(title="mission-control: fleet")

ROBOT_IDS = ["go2", "xavier"]

_start_t = time.time()


def _mock_state(robot_id: str) -> dict:
    t = time.time() - _start_t
    phase = 0.0 if robot_id == "go2" else math.pi
    x = 2.0 * math.sin(t * 0.1 + phase)
    y = 2.0 * math.cos(t * 0.1 + phase)
    yaw = (t * 0.05 + phase) % (2 * math.pi)
    battery_pct = max(0.0, 100.0 - (t * 0.01) % 100.0)
    return {
        "robot_id": robot_id,
        "connected": True,
        "armed": False,
        "pose": {
            "x": round(x, 3),
            "y": round(y, 3),
            "z": 0.0,
            "yaw": round(yaw, 3),
            "level_id": "ground",
            "t": time.time(),
        },
        "battery": {
            "voltage": round(22.0 + 0.06 * battery_pct, 2),
            "current": round(0.4 + 0.3 * random.random(), 2),
            "percent": round(battery_pct, 1),
            "t": time.time(),
        },
        "status": "idle",
        "current_task_id": None,
        "t": time.time(),
    }


@app.get("/robots/go2/state")
def go2_state():
    return _mock_state("go2")


@app.get("/robots/xavier/state")
def xavier_state():
    return _mock_state("xavier")


@app.get("/robots")
def list_robots():
    return {"robots": ROBOT_IDS}


@app.get("/robots/{robot_id}/state")
def robot_state(robot_id: str):
    if robot_id not in ROBOT_IDS:
        raise HTTPException(status_code=404, detail="unknown robot_id")
    return _mock_state(robot_id)


@app.get("/health")
def health():
    return {"ok": True, "robots": ROBOT_IDS}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9111)
