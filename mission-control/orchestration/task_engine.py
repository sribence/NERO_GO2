"""Task engine: sequential step execution for the orchestration pillar.

Kept free of FastAPI/WS/MQTT wiring so it can be imported and unit tested
on its own. `app.py` owns the HTTP/WS/MQTT surface and wires an
`event_publish` callback (Redis publish, WS broadcast, MQTT publish, JSONL
log) into `TaskEngine`.

Step types (see README.md for full examples):
  {"goto": [x, y]}
  {"call_api": {"url": ..., "method": "GET|POST", "body": {...}, "headers": {...}},
   "wait_for": "response", "timeout_s": 30}
  {"sensor": "photo" | "lidar_scan" | "thermal"}
  {"play_sound": "<event_name>"}
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

# Tasks arrive from REST, WebSocket AND an anonymous MQTT topic, so an
# unrestricted call_api step turns this service into an SSRF pivot onto the
# robot's own network (AUDIT-2026-09-10.md, P0-8).
ALLOWED_API_HOSTS = {h.strip() for h in os.environ.get("ALLOWED_API_HOSTS", "").split(",") if h.strip()}
ALLOW_PRIVATE_API_HOSTS = os.environ.get("ALLOW_PRIVATE_API_HOSTS", "0") == "1"


class StepStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class StepResult:
    index: int
    step: dict
    status: str = StepStatus.PENDING.value
    detail: Any = None
    result: Any = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Task:
    id: str
    steps: list
    status: str = TaskStatus.PENDING.value
    step_results: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "steps": [sr.to_dict() for sr in self.step_results],
        }


# Type of the event publish hook: (task_id, step_index, step_type, status, detail) -> None
EventPublisher = Callable[[str, int, str, str, Any], None]


class StepError(Exception):
    pass


def validate_outbound_url(url: str) -> None:
    """Gate for the call_api step's target. Raises StepError if not allowed."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise StepError(f"call_api: only http/https allowed, got {p.scheme!r}")
    if not p.hostname:
        raise StepError("call_api: missing hostname")
    if ALLOWED_API_HOSTS and p.hostname not in ALLOWED_API_HOSTS:
        raise StepError(f"call_api: {p.hostname} is not in ALLOWED_API_HOSTS")
    if ALLOW_PRIVATE_API_HOSTS:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror as exc:
        raise StepError(f"call_api: DNS resolution failed: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise StepError(f"call_api: internal address blocked ({ip})")


class TaskEngine:
    """Owns task storage and sequential step execution.

    `robot`: a RobotClient instance (from core.robot_client.get_robot_client())
        used for the `goto` step's arm check and as a general safety gate.
    `navigation_url`, `sensors_url`, `audio_url`: base URLs for the sibling
        services this engine calls out to.
    `event_publish`: optional callback invoked on every step transition.
    `http_get`/`http_post`: overridable for testing.
    """

    def __init__(
        self,
        navigation_url: str,
        sensors_url: str,
        audio_url: str,
        robot=None,
        event_publish: Optional[EventPublisher] = None,
        session: Optional[requests.Session] = None,
    ):
        self.navigation_url = navigation_url.rstrip("/")
        self.sensors_url = sensors_url.rstrip("/")
        self.audio_url = audio_url.rstrip("/")
        self.robot = robot
        self.event_publish = event_publish or (lambda *a, **k: None)
        self.session = session or requests.Session()
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- task store

    def create_task(self, steps: list[dict]) -> Task:
        task_id = str(uuid.uuid4())
        step_results = [StepResult(index=i, step=s) for i, s in enumerate(steps)]
        task = Task(id=task_id, steps=steps, step_results=step_results)
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def run_task_async(self, task: Task) -> threading.Thread:
        t = threading.Thread(target=self.run_task, args=(task,), daemon=True)
        t.start()
        return t

    # ------------------------------------------------------------ execute

    def run_task(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING.value
        for i, step in enumerate(task.steps):
            sr = task.step_results[i]
            step_type = _step_type(step)
            sr.status = StepStatus.STARTED.value
            sr.started_at = time.time()
            self._emit(task.id, i, step_type, StepStatus.STARTED.value, None)
            try:
                result = self._execute_step(step)
                sr.status = StepStatus.SUCCEEDED.value
                sr.result = result
                sr.detail = "ok"
                sr.finished_at = time.time()
                self._emit(task.id, i, step_type, StepStatus.SUCCEEDED.value, result)
            except Exception as exc:  # noqa: BLE001 - step failures are data, not crashes
                sr.status = StepStatus.FAILED.value
                sr.detail = str(exc)
                sr.finished_at = time.time()
                self._emit(task.id, i, step_type, StepStatus.FAILED.value, str(exc))
                task.status = TaskStatus.FAILED.value
                task.finished_at = time.time()
                return task
        task.status = TaskStatus.SUCCEEDED.value
        task.finished_at = time.time()
        return task

    def _emit(self, task_id: str, index: int, step_type: str, status: str, detail: Any):
        try:
            self.event_publish(task_id, index, step_type, status, detail)
        except Exception:
            pass  # event publishing must never break task execution

    def _execute_step(self, step: dict) -> Any:
        if "goto" in step:
            return self._step_goto(step)
        if "call_api" in step:
            return self._step_call_api(step)
        if "sensor" in step:
            return self._step_sensor(step)
        if "play_sound" in step:
            return self._step_play_sound(step)
        raise StepError(f"unknown step type, keys={list(step.keys())}")

    # ------------------------------------------------------------- steps

    def _step_goto(self, step: dict) -> dict:
        xy = step["goto"]
        if not (isinstance(xy, (list, tuple)) and len(xy) == 2):
            raise StepError("goto requires [x, y]")
        x, y = float(xy[0]), float(xy[1])

        # The safety gate this engine's docstring promised but never applied:
        # a task must not be able to start motion on a disarmed robot.
        if self.robot is not None and not self.robot.is_armed():
            raise StepError("robot is not armed, refusing goto")

        resp = self.session.post(f"{self.navigation_url}/goto", json={"x": x, "y": y}, timeout=10)
        resp.raise_for_status()

        timeout_s = float(step.get("timeout_s", 120))
        poll_interval = float(step.get("poll_interval_s", 1.0))
        deadline = time.time() + timeout_s
        last_status: dict = {}
        while time.time() < deadline:
            r = self.session.get(f"{self.navigation_url}/nav_status", timeout=10)
            r.raise_for_status()
            last_status = r.json()
            state = str(last_status.get("state", "")).lower()
            if state in ("done", "succeeded", "success"):
                return {"nav_status": last_status}
            if state in ("failed", "error", "aborted"):
                raise StepError(f"navigation failed: {last_status}")
            time.sleep(poll_interval)
        raise StepError(f"goto timed out after {timeout_s}s, last_status={last_status}")

    def _step_call_api(self, step: dict) -> dict:
        cfg = step["call_api"]
        url = cfg["url"]
        validate_outbound_url(url)
        method = str(cfg.get("method", "GET")).upper()
        body = cfg.get("body")
        headers = cfg.get("headers") or {}
        timeout_s = float(step.get("timeout_s", 30))

        try:
            resp = self.session.request(
                method, url, json=body, headers=headers, timeout=timeout_s
            )
        except requests.exceptions.Timeout as exc:
            raise StepError(f"call_api timed out after {timeout_s}s: {exc}") from exc
        except requests.exceptions.RequestException as exc:
            raise StepError(f"call_api request failed: {exc}") from exc

        try:
            parsed = resp.json()
        except ValueError:
            parsed = resp.text

        if resp.status_code >= 400:
            raise StepError(f"call_api got HTTP {resp.status_code}: {parsed}")

        return {"status_code": resp.status_code, "response": parsed}

    def _step_sensor(self, step: dict) -> dict:
        kind = step["sensor"]
        # Singular "/sensor/..." -- this is what sensors/app.py actually
        # mounts; the plural form here returned 404 for every sensor step
        # (AUDIT-2026-09-10.md, P1-1).
        endpoint_map = {
            "photo": "/sensor/photo",
            "lidar_scan": "/sensor/lidar_scan",
            "thermal": "/sensor/thermal",
        }
        if kind not in endpoint_map:
            raise StepError(f"unknown sensor type: {kind}")
        timeout_s = float(step.get("timeout_s", 30))
        resp = self.session.post(f"{self.sensors_url}{endpoint_map[kind]}", timeout=timeout_s)
        resp.raise_for_status()
        try:
            parsed = resp.json()
        except ValueError:
            parsed = {"raw": resp.text}
        return {"sensor": kind, "result": parsed}

    def _step_play_sound(self, step: dict) -> dict:
        event_name = step["play_sound"]
        timeout_s = float(step.get("timeout_s", 10))
        resp = self.session.post(f"{self.audio_url}/audio/play/{event_name}", timeout=timeout_s)
        resp.raise_for_status()
        try:
            parsed = resp.json()
        except ValueError:
            parsed = {"raw": resp.text}
        return {"event": event_name, "result": parsed}


def _step_type(step: dict) -> str:
    for key in ("goto", "call_api", "sensor", "play_sound"):
        if key in step:
            return key
    return "unknown"
