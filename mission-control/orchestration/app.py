"""Orchestration pillar — task engine + protocol gateway (port 9104).

Lets other systems drive the robot through a sequential task pipeline via
three protocols that all funnel into the same `TaskEngine`:
  - REST:      POST /task, GET /task/{id}/status
  - WebSocket: WS /ws
  - MQTT:      subscribe missioncontrol/task/submit, publish missioncontrol/task/events

Per CONVENTIONS.md: JSONL logs to logs/events.jsonl, Redis event bus
channel `mc.orchestration.task_event`, does not touch DDS/WebRTC directly
(delegates robot motion to the `navigation` pillar's REST API).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uvicorn

from task_engine import TaskEngine, Task

# --------------------------------------------------------------------------- config

NAVIGATION_URL = os.environ.get("NAVIGATION_URL", "http://navigation:9103")
SENSORS_URL = os.environ.get("SENSORS_URL", "http://sensors:9105")
AUDIO_URL = os.environ.get("AUDIO_URL", "http://audio:9107")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "mqtt")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))

TASK_EVENT_CHANNEL = "mc.orchestration.task_event"
MQTT_SUBMIT_TOPIC = "missioncontrol/task/submit"
MQTT_EVENTS_TOPIC = "missioncontrol/task/events"

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "events.jsonl")
_log_lock = threading.Lock()


def log_event(level: str, msg: str, **extra) -> None:
    record = {"t": time.time(), "pillar": "orchestration", "level": level, "msg": msg}
    record.update(extra)
    line = json.dumps(record, default=str)
    with _log_lock:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    print(line, flush=True)


# --------------------------------------------------------------------------- redis

redis_client = None
try:
    import redis as redis_lib

    redis_client = redis_lib.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2
    )
    redis_client.ping()
    log_event("info", f"connected to redis at {REDIS_HOST}:{REDIS_PORT}")
except Exception as exc:  # noqa: BLE001
    log_event("warn", f"redis unavailable at startup, continuing without it: {exc}")
    redis_client = None


def redis_publish(channel: str, payload: dict) -> None:
    global redis_client
    if redis_client is None:
        return
    try:
        redis_client.publish(channel, json.dumps(payload, default=str))
    except Exception as exc:  # noqa: BLE001
        log_event("warn", f"redis publish failed, dropping connection: {exc}")
        redis_client = None


# --------------------------------------------------------------------------- mqtt

mqtt_client = None
_mqtt_stop = threading.Event()

try:
    import paho.mqtt.client as mqtt

    def _on_mqtt_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            log_event("info", f"mqtt connected to {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
            client.subscribe(MQTT_SUBMIT_TOPIC)
        else:
            log_event("warn", f"mqtt connect returned rc={rc}")

    def _on_mqtt_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            steps = payload.get("steps")
            if not steps:
                log_event("warn", "mqtt submit missing 'steps'", topic=msg.topic)
                return
            task = engine.create_task(steps)
            log_event("info", "task submitted via mqtt", task_id=task.id)
            engine.run_task_async(task)
        except Exception as exc:  # noqa: BLE001
            log_event("error", f"mqtt submit handling failed: {exc}")

    def _mqtt_connect_loop():
        backoff = 2.0
        try:
            client = mqtt.Client(
                client_id=f"orchestration-{uuid.uuid4().hex[:8]}",
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )
        except AttributeError:
            # older paho-mqtt without CallbackAPIVersion
            client = mqtt.Client(client_id=f"orchestration-{uuid.uuid4().hex[:8]}")
        client.on_connect = _on_mqtt_connect
        client.on_message = _on_mqtt_message

        global mqtt_client
        mqtt_client = client

        while not _mqtt_stop.is_set():
            try:
                client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=30)
                backoff = 2.0
                client.loop_forever(retry_first_connection=False)
            except Exception as exc:  # noqa: BLE001
                log_event("warn", f"mqtt broker unavailable, retrying in {backoff:.0f}s: {exc}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    threading.Thread(target=_mqtt_connect_loop, daemon=True).start()
except ImportError:
    log_event("warn", "paho-mqtt not installed, mqtt bridge disabled")
    mqtt_client = None


def mqtt_publish(topic: str, payload: dict) -> None:
    if mqtt_client is None:
        return
    try:
        if mqtt_client.is_connected():
            mqtt_client.publish(topic, json.dumps(payload, default=str))
    except Exception as exc:  # noqa: BLE001
        log_event("warn", f"mqtt publish failed: {exc}")


# --------------------------------------------------------------------------- ws bridge

ws_queues: set[asyncio.Queue] = set()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_to_ws(payload: dict) -> None:
    """Called from any thread; hands the payload to each connected websocket's queue."""
    if _main_loop is None:
        return
    for q in list(ws_queues):
        try:
            asyncio.run_coroutine_threadsafe(q.put(payload), _main_loop)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- engine

def on_task_event(task_id: str, step_index: int, step_type: str, status: str, detail) -> None:
    payload = {
        "task_id": task_id,
        "step_index": step_index,
        "step_type": step_type,
        "status": status,
        "detail": detail,
        "t": time.time(),
    }
    log_event("info", f"task step {status}", **payload)
    redis_publish(TASK_EVENT_CHANNEL, payload)
    mqtt_publish(MQTT_EVENTS_TOPIC, payload)
    broadcast_to_ws(payload)


try:
    from robot_client import get_robot_client

    _robot = get_robot_client()
except Exception as exc:  # noqa: BLE001
    log_event("warn", f"robot client unavailable, goto arm-gate disabled: {exc}")
    _robot = None

engine = TaskEngine(
    navigation_url=NAVIGATION_URL,
    sensors_url=SENSORS_URL,
    audio_url=AUDIO_URL,
    robot=_robot,
    event_publish=on_task_event,
)

# --------------------------------------------------------------------------- fastapi

app = FastAPI(title="mission-control: orchestration")


class TaskRequest(BaseModel):
    steps: list[dict]


@app.on_event("startup")
async def _on_startup():
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    log_event("info", "orchestration service starting", port=9104)


@app.post("/task")
def create_task(req: TaskRequest):
    task = engine.create_task(req.steps)
    log_event("info", "task submitted via rest", task_id=task.id, n_steps=len(req.steps))
    engine.run_task_async(task)
    return {"task_id": task.id}


@app.get("/task/{task_id}/status")
def task_status(task_id: str):
    task = engine.get_task(task_id)
    if task is None:
        return {"error": "not_found", "task_id": task_id}
    return task.to_dict()


@app.get("/health")
def health():
    return {
        "ok": True,
        "redis": redis_client is not None,
        "mqtt": mqtt_client.is_connected() if mqtt_client is not None else False,
    }


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    ws_queues.add(queue)

    async def sender():
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)

    sender_task = asyncio.create_task(sender())
    try:
        while True:
            data = await websocket.receive_json()
            steps = data.get("steps")
            if not steps:
                await websocket.send_json({"error": "steps required"})
                continue
            task = engine.create_task(steps)
            log_event("info", "task submitted via ws", task_id=task.id, n_steps=len(steps))
            engine.run_task_async(task)
            await websocket.send_json({"task_id": task.id})
    except WebSocketDisconnect:
        pass
    finally:
        ws_queues.discard(queue)
        sender_task.cancel()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9104)
