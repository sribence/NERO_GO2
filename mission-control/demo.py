"""mission-control DEMO -- the whole operator console, no robot, no Docker.

Purpose: let a human look at the real UI, on a phone or a laptop, and see
every state it can show (battery levels, arming, proximity warnings, the
safety brake, navigation, the alert hierarchy) without a Go2, without
Redis/MQTT and without the Docker stack.

It serves the SAME `digital-twin/static/` files the real pillar serves, so
what you see here is the actual interface, not a mockup of it. Only the
data behind it is synthetic -- and it says so: every payload carries
`"demo": true`, which lights up a DEMO badge in the header.

    python demo.py

Then open the printed URL. On a phone, use the LAN address on the same
WiFi. Nothing here can move a physical robot: there is no robot client,
no DDS and no WebRTC import anywhere in this file.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "digital-twin", "static")

PORT = int(os.environ.get("DEMO_PORT", "9110"))
RES = 0.05
W = H = 200
ORIGIN_X = ORIGIN_Y = -5.0
REVEAL_RADIUS_M = 2.6

app = FastAPI(title="mission-control: DEMO")


# ---------------------------------------------------------------------------
# Synthetic floor plan
# ---------------------------------------------------------------------------

def _blank(fill):
    return [fill] * (W * H)


def _idx(gx, gy):
    return gy * W + gx


def _w2g(x, y):
    return int((x - ORIGIN_X) / RES), int((y - ORIGIN_Y) / RES)


def _g2w(gx, gy):
    return ORIGIN_X + (gx + 0.5) * RES, ORIGIN_Y + (gy + 0.5) * RES


truth_floor = _blank(0)     # 0 free, 100 occupied
truth_walls = _blank(0)     # 0..255 height bucket


def _fill_rect(x0, y0, x1, y1, height_m):
    """Mark a world-space rectangle as an obstacle of the given height."""
    gx0, gy0 = _w2g(min(x0, x1), min(y0, y1))
    gx1, gy1 = _w2g(max(x0, x1), max(y0, y1))
    bucket = min(255, 30 + int(round(min(height_m, 2.5) / 2.5 * 225)))
    for gy in range(max(0, gy0), min(H, gy1 + 1)):
        for gx in range(max(0, gx0), min(W, gx1 + 1)):
            truth_floor[_idx(gx, gy)] = 100
            truth_walls[_idx(gx, gy)] = max(truth_walls[_idx(gx, gy)], bucket)


def _build_floorplan():
    T = 0.12  # wall thickness
    # Outer shell (a ~9 x 9 m flat)
    _fill_rect(-4.5, -4.5, 4.5, -4.5 + T, 2.4)
    _fill_rect(-4.5, 4.5 - T, 4.5, 4.5, 2.4)
    _fill_rect(-4.5, -4.5, -4.5 + T, 4.5, 2.4)
    _fill_rect(4.5 - T, -4.5, 4.5, 4.5, 2.4)
    # Vertical partition at x = 0 with a doorway between y = -0.6 and 0.8
    _fill_rect(-T / 2, -4.5, T / 2, -0.6, 2.4)
    _fill_rect(-T / 2, 0.8, T / 2, 4.5, 2.4)
    # Horizontal partition on the right half, doorway near x = 3.2
    _fill_rect(0, 1.6, 2.6, 1.6 + T, 2.4)
    _fill_rect(3.8, 1.6, 4.5, 1.6 + T, 2.4)
    # Furniture -- deliberately below 1 m, the exact band that used to be
    # misread as "stairs" and planned straight through (audit P0-1).
    _fill_rect(-3.9, -3.9, -2.4, -2.6, 0.75)   # desk
    _fill_rect(-4.0, 1.2, -2.8, 3.0, 0.45)     # sofa
    _fill_rect(1.2, -3.6, 2.6, -2.2, 0.72)     # table
    _fill_rect(3.2, -1.2, 4.2, 0.4, 1.85)      # shelf
    _fill_rect(0.9, 2.6, 2.0, 3.8, 0.9)        # cabinet


_build_floorplan()

revealed = [False] * (W * H)
_map_version = 0
_map_lock = threading.Lock()


def _reveal_around(x, y):
    """Simulate a LiDAR sweep revealing cells around the robot."""
    global _map_version
    r_cells = int(REVEAL_RADIUS_M / RES)
    cgx, cgy = _w2g(x, y)
    changed = False
    for gy in range(max(0, cgy - r_cells), min(H, cgy + r_cells + 1)):
        for gx in range(max(0, cgx - r_cells), min(W, cgx + r_cells + 1)):
            if (gx - cgx) ** 2 + (gy - cgy) ** 2 > r_cells * r_cells:
                continue
            i = _idx(gx, gy)
            if not revealed[i]:
                revealed[i] = True
                changed = True
    if changed:
        with _map_lock:
            _map_version += 1


def map_payload() -> dict:
    floor = [truth_floor[i] if revealed[i] else -1 for i in range(W * H)]
    walls = [truth_walls[i] if revealed[i] else 0 for i in range(W * H)]
    return {
        "resolution": RES, "origin_x": ORIGIN_X, "origin_y": ORIGIN_Y,
        "width": W, "height": H, "level_id": "ground",
        "floor": floor, "walls": walls,
    }


# ---------------------------------------------------------------------------
# Synthetic robot + scenario
# ---------------------------------------------------------------------------

PATROL = [(-3.2, -3.0), (-3.2, 3.4), (-1.0, 3.4), (-1.0, 0.2),
          (2.0, 0.2), (3.6, -3.2), (-1.0, -3.4), (-1.0, 0.2)]


class DemoRobot:
    """A scripted robot. The scenario cycles through every UI state on a
    ~110 s loop so an operator can see each one without staging it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.x, self.y = PATROL[0]
        self.yaw = math.pi / 2
        self.battery = 86.0
        self.armed = True
        self.nav_state = "moving"
        self.nav_error = None
        self.goal = None
        self.wp = 1
        self.proximity_m = None
        self.proximity_active = False
        self.estopped = False
        self.estop_t = 0.0
        # Demo-only: recover on its own so hitting E-STOP doesn't leave the
        # console permanently frozen for the next person who looks at it.
        self.estop_recover_s = float(os.environ.get("DEMO_ESTOP_RECOVER_S", "12"))
        self.t0 = time.time()
        threading.Thread(target=self._loop, daemon=True, name="demo-robot").start()

    # -- operator commands -------------------------------------------
    def goto(self, x, y):
        with self.lock:
            if not self.armed:
                return False, "robot is not armed"
            self.goal = (x, y)
            self.nav_state = "moving"
            self.nav_error = None
            self.estopped = False
            return True, None

    def cancel(self):
        with self.lock:
            self.goal = None
            self.nav_state = "idle"

    def estop(self):
        with self.lock:
            self.estopped = True
            self.estop_t = time.time()
            self.armed = False
            self.goal = None
            self.nav_state = "idle"

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "pose": {"x": round(self.x, 3), "y": round(self.y, 3), "z": 0.0,
                          "yaw": round(self.yaw, 4), "level_id": "ground", "t": time.time()},
                "battery": {"voltage": round(22.0 + 0.06 * self.battery, 2),
                             "current": round(1.6 + 0.4 * random.random(), 2),
                             "percent": round(self.battery, 1), "t": time.time()},
                "imu": {"roll": round(0.02 * math.sin(time.time() * 1.3), 4),
                         "pitch": round(0.02 * math.sin(time.time() * 0.9), 4),
                         "yaw": round(self.yaw, 4), "accel_z": 9.81, "t": time.time()},
                "armed": self.armed,
                "link": {"tracked": True, "healthy": True, "age_s": 0.05},
                "proximity": {"active": self.proximity_active,
                               "min_distance_m": (round(self.proximity_m, 2)
                                                  if self.proximity_m is not None else None),
                               "t": time.time()},
                "nav_state": self.nav_state,
                "nav_error": self.nav_error,
                "localization_confidence": None,   # honestly absent, not a fake 50%
                "demo": True,
                "t": time.time(),
            }

    # -- scenario ----------------------------------------------------
    def _scenario(self, phase: float):
        """phase in [0, 1) over a ~110 s cycle."""
        # 0.00-0.55 normal patrol
        # 0.55-0.65 someone walks close -> proximity warning
        # 0.65-0.75 safety brake -> nav_state "blocked"
        # 0.75-0.85 battery drops into the low band
        # 0.85-0.93 battery critical
        # 0.93-1.00 recovers (as if swapped/charged)
        if 0.55 <= phase < 0.65:
            self.proximity_m = 0.35 + 0.3 * math.sin(phase * 120)
            self.proximity_active = True
        else:
            self.proximity_m = 1.4 + 0.8 * math.sin(phase * 30)
            self.proximity_active = False

        if 0.65 <= phase < 0.75:
            if not self.estopped:
                self.nav_state = "blocked"
        elif not self.estopped and self.nav_state == "blocked":
            self.nav_state = "moving"

        if 0.75 <= phase < 0.85:
            self.battery = min(self.battery, 17.0)
        elif 0.85 <= phase < 0.93:
            self.battery = min(self.battery, 7.5)
        elif phase >= 0.93:
            self.battery = 86.0

    def _loop(self):
        last = time.time()
        while True:
            time.sleep(0.05)
            now = time.time()
            dt = now - last
            last = now
            phase = ((now - self.t0) % 110.0) / 110.0

            with self.lock:
                self._scenario(phase)

                if self.estopped and (now - self.estop_t) > self.estop_recover_s:
                    self.estopped = False
                    self.armed = True
                    self.nav_state = "moving"

                if self.estopped or self.nav_state == "blocked" or not self.armed:
                    _reveal_around(self.x, self.y)
                    continue

                if self.goal is not None:
                    tx, ty = self.goal
                else:
                    tx, ty = PATROL[self.wp]

                dx, dy = tx - self.x, ty - self.y
                dist = math.hypot(dx, dy)
                if dist < 0.14:
                    if self.goal is not None:
                        self.goal = None
                        self.nav_state = "done"
                    else:
                        self.wp = (self.wp + 1) % len(PATROL)
                    continue

                if self.nav_state in ("idle", "done") and self.goal is None:
                    self.nav_state = "moving"

                target_yaw = math.atan2(dy, dx)
                err = (target_yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
                self.yaw += max(-1.6 * dt, min(1.6 * dt, err * 2.4))
                speed = 0.55 * max(0.15, 1.0 - abs(err) / math.pi)
                self.x += speed * math.cos(self.yaw) * dt
                self.y += speed * math.sin(self.yaw) * dt
                self.battery = max(0.0, self.battery - 0.012 * dt)

                _reveal_around(self.x, self.y)


robot = DemoRobot()


# ---------------------------------------------------------------------------
# The same API surface digital-twin/server.py exposes
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"ok": True, "pillar": "demo", "demo": True}


@app.get("/api/map_proxy")
def map_proxy():
    return JSONResponse(content=map_payload())


@app.get("/api/state")
def state():
    return JSONResponse(content=robot.snapshot())


@app.post("/api/goto")
async def goto(body: dict):
    x, y = body.get("x"), body.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return JSONResponse(status_code=400, content={"error": "numeric x and y required"})
    ok, err = robot.goto(float(x), float(y))
    if not ok:
        return JSONResponse(status_code=409, content={"detail": err})
    return {"nav_id": "demo", "state": "moving"}


@app.post("/api/goto/cancel")
def goto_cancel():
    robot.cancel()
    return {"state": "cancelled"}


@app.post("/api/estop")
def estop():
    robot.estop()
    return {"estop": True, "armed": False}


@app.post("/api/_demo/arm")
def demo_arm():
    """Demo-only: re-arm after an E-stop so the console can be tried again."""
    with robot.lock:
        robot.armed = True
        robot.estopped = False
        robot.nav_state = "moving"
    return {"armed": True}


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = robot.snapshot()
            with _map_lock:
                payload["map_version"] = _map_version
            payload["map_error"] = None
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ip = _lan_ip()
    print("\n" + "=" * 62)
    print("  mission-control DEMO  --  synthetic data, no robot involved")
    print("=" * 62)
    print(f"  This computer : http://localhost:{PORT}/")
    print(f"  Phone on WiFi : http://{ip}:{PORT}/")
    print("=" * 62 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
