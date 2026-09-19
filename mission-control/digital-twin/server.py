"""mission-control: digital-twin pillar (port 9110).

The Unity-like 3D operator console. Renders the dual-layer map produced by
the `mapping` pillar, shows live robot state from `core`, and lets an
operator send the robot to a point on the floor.

Endpoints:
    GET  /                     -- static single-page app (index.html)
    GET  /api/map_proxy        -- proxies + briefly caches mapping's GET /map
    GET  /api/state            -- combined core + navigation state for the HUD
    POST /api/goto             -- proxies navigation's POST /goto
    POST /api/goto/cancel      -- proxies navigation's POST /goto/cancel
    POST /api/estop            -- proxies core's POST /estop (never authenticated)
    WS   /ws/live              -- pushes the combined state ~2x/sec

Talks to other pillars only over HTTP (this pillar has no direct robot
access and does not import robot_client.py -- it is a pure viewer/proxy).
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

PILLAR = "digital-twin"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "events.jsonl")

os.makedirs(LOGS_DIR, exist_ok=True)

MAPPING_URL = os.environ.get("MAPPING_URL", "http://mapping:9102")
CORE_URL = os.environ.get("CORE_URL", "http://core:9101")
NAVIGATION_URL = os.environ.get("NAVIGATION_URL", "http://navigation:9103")
API_TOKEN = os.environ.get("MC_API_TOKEN", "")

MAP_CACHE_TTL_S = 0.3

app = FastAPI(title="mission-control: digital-twin")

# One shared client: a new AsyncClient per request throws away the
# connection pool on every poll, twice a second, per connected browser.
_http = httpx.AsyncClient(timeout=2.0, headers={"X-MC-Token": API_TOKEN} if API_TOKEN else None)


def log_event(level: str, msg: str, **extra) -> None:
    record = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Map proxy with a short cache
# ---------------------------------------------------------------------------
_map_cache: dict = {"data": None, "ts": 0.0, "sig": None}
_map_version = 0


async def _fetch_map(force: bool = False) -> dict:
    global _map_version
    now = time.time()
    if not force and _map_cache["data"] is not None and (now - _map_cache["ts"]) < MAP_CACHE_TTL_S:
        return {"ok": True, "map": _map_cache["data"]}
    try:
        resp = await _http.get(f"{MAPPING_URL}/map")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 -- mapping may not be up yet
        log_event("warn", "map_proxy fetch failed", error=str(exc))
        return {"ok": False, "error": f"mapping service unreachable: {exc}"}

    # Compare a cheap signature instead of the whole 40k-cell payload.
    sig = (len(data.get("floor", ())), sum(data.get("floor", ())), sum(data.get("walls", ())))
    if sig != _map_cache["sig"]:
        _map_version += 1
        _map_cache["sig"] = sig
    _map_cache["data"] = data
    _map_cache["ts"] = now
    return {"ok": True, "map": data}


async def _fetch_state() -> dict:
    """Combined core + navigation snapshot -- one payload for the whole HUD."""
    out: dict = {
        "pose": None, "battery": None, "imu": None, "armed": None,
        "link": None, "proximity": None,
        "nav_state": None, "nav_error": None,
        "localization_confidence": None,
        "demo": False,
        "t": time.time(),
    }
    try:
        r = await _http.get(f"{CORE_URL}/state")
        r.raise_for_status()
        s = r.json()
        out.update(pose=s.get("pose"), battery=s.get("battery"), imu=s.get("imu"),
                   armed=s.get("armed"), link=s.get("link"), proximity=s.get("proximity"))
    except Exception as exc:  # noqa: BLE001
        out["link"] = {"tracked": True, "healthy": False, "age_s": None}
        out["core_error"] = str(exc)
    try:
        r = await _http.get(f"{NAVIGATION_URL}/nav_status")
        r.raise_for_status()
        n = r.json()
        out.update(nav_state=n.get("state"), nav_error=n.get("error"))
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"ok": True, "pillar": PILLAR}


@app.get("/api/map_proxy")
async def map_proxy():
    result = await _fetch_map()
    if not result["ok"]:
        return JSONResponse(status_code=503, content={"error": result["error"]})
    return JSONResponse(content=result["map"])


@app.get("/api/state")
async def state():
    return JSONResponse(content=await _fetch_state())


@app.post("/api/goto")
async def goto(body: dict):
    x, y = body.get("x"), body.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return JSONResponse(status_code=400, content={"error": "body must include numeric x and y"})
    try:
        resp = await _http.post(f"{NAVIGATION_URL}/goto", json={"x": x, "y": y}, timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        log_event("warn", "goto proxy failed", error=str(exc), x=x, y=y)
        return JSONResponse(status_code=503, content={"error": f"navigation unreachable: {exc}"})
    log_event("info", "goto issued", x=x, y=y, status_code=resp.status_code)
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": resp.text}
    return JSONResponse(status_code=resp.status_code, content=payload)


@app.post("/api/goto/cancel")
async def goto_cancel():
    try:
        resp = await _http.post(f"{NAVIGATION_URL}/goto/cancel", timeout=5.0)
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"error": str(exc)})


@app.post("/api/estop")
async def estop():
    """Emergency stop passthrough. Kept as short and dependency-free as
    possible: this is the one request that must work when everything else
    is degraded."""
    try:
        resp = await _http.post(f"{CORE_URL}/estop", timeout=2.0)
        log_event("warn", "ESTOP issued from operator console", status_code=resp.status_code)
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as exc:  # noqa: BLE001
        log_event("error", "ESTOP proxy FAILED", error=str(exc))
        return JSONResponse(status_code=503, content={"error": f"core unreachable: {exc}"})


# ---------------------------------------------------------------------------
# WebSocket: pushes the combined state to connected browsers every ~500ms
# ---------------------------------------------------------------------------
@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = await _fetch_state()
            map_result = await _fetch_map()  # cached, cheap
            payload["map_version"] = _map_version if map_result["ok"] else None
            payload["map_error"] = None if map_result["ok"] else map_result["error"]
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log_event("warn", "ws_live loop error", error=str(exc))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    log_event("info", "digital-twin starting", port=9110)
    uvicorn.run(app, host="0.0.0.0", port=9110)
