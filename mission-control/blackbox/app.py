"""mission-control: blackbox pillar (port 9108) -- the flight recorder.

A small, bounded, self-pruning rolling buffer of telemetry + camera frames
that survives crashes/incidents by promoting the relevant slice to
permanent storage BEFORE it would be pruned.

Threads:
    recorder_loop   -- polls robot.get_pose()/get_battery()/get_imu() every
                        ~1s, appends to buffer/rolling.jsonl; grabs one
                        camera frame every ~5s into buffer/frames/.
    pruning_loop    -- enforces RETENTION_SECONDS / MAX_BUFFER_MB on the
                        rolling buffer (retention.prune_buffer).
    anomaly_loop    -- watches the telemetry recorder_loop just captured for
                        battery-drop-rate, IMU "impact" jumps, and dead
                        polling; promotes an incident on any hit.
    redis_subscribe_loop -- subscribes to mc.core.anomaly per CONVENTIONS.md
                        as another incident trigger source.

Talks to the robot only through core/robot_client.py, per CONVENTIONS.md.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import redis
import uvicorn

from robot_client import get_robot_client

import retention

PILLAR = "blackbox"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUFFER_DIR = os.path.join(BASE_DIR, "buffer")
INCIDENTS_DIR = os.path.join(BASE_DIR, "incidents")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "events.jsonl")

os.makedirs(LOGS_DIR, exist_ok=True)
retention.ensure_buffer_dirs(BUFFER_DIR)
os.makedirs(INCIDENTS_DIR, exist_ok=True)

# --- env / tuning ------------------------------------------------------

RETENTION_SECONDS = float(os.environ.get("RETENTION_SECONDS", "600"))
MAX_BUFFER_MB = float(os.environ.get("MAX_BUFFER_MB", "200"))
MAX_BUFFER_BYTES = int(MAX_BUFFER_MB * 1024 * 1024)
INCIDENT_WINDOW_SECONDS = float(os.environ.get("INCIDENT_WINDOW_SECONDS", "30"))

RECORD_INTERVAL_SECONDS = float(os.environ.get("RECORD_INTERVAL_SECONDS", "1.0"))
FRAME_INTERVAL_SECONDS = float(os.environ.get("FRAME_INTERVAL_SECONDS", "5.0"))
PRUNE_INTERVAL_SECONDS = float(os.environ.get("PRUNE_INTERVAL_SECONDS", "5.0"))
ANOMALY_CHECK_INTERVAL_SECONDS = float(os.environ.get("ANOMALY_CHECK_INTERVAL_SECONDS", "1.0"))
ANOMALY_COOLDOWN_SECONDS = float(os.environ.get("ANOMALY_COOLDOWN_SECONDS", "30"))

POLL_FAILURE_THRESHOLD = int(os.environ.get("POLL_FAILURE_THRESHOLD", "5"))
BATTERY_DROP_PCT_PER_SEC = float(os.environ.get("BATTERY_DROP_PCT_PER_SEC", "2.0"))
ACCEL_Z_JUMP_THRESHOLD = float(os.environ.get("ACCEL_Z_JUMP_THRESHOLD", "3.0"))
ROLL_PITCH_JUMP_THRESHOLD_RAD = float(os.environ.get("ROLL_PITCH_JUMP_THRESHOLD_RAD", "0.5"))

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# --- app / robot / redis ------------------------------------------------

app = FastAPI(title="mission-control: blackbox")
app.mount("/incidents_files", StaticFiles(directory=INCIDENTS_DIR), name="incidents_files")

robot = get_robot_client()
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

_shutdown = threading.Event()


def log_event(level: str, msg: str, **extra) -> None:
    """Append one JSONL line per CONVENTIONS.md log format.

    This is the blackbox SERVICE's own operational log (logs/events.jsonl)
    -- separate from buffer/rolling.jsonl, which is the robot telemetry
    buffer this service manages.
    """
    record = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


# --- shared telemetry snapshot (written by recorder_loop, read by
#     anomaly_loop / /buffer/status) ---------------------------------

_telemetry_lock = threading.Lock()
_latest = {
    "pose": None,
    "battery": None,
    "imu": None,
    "poll_failures": 0,
    "last_poll_ok_t": time.time(),
}

_incident_lock = threading.Lock()
_last_incident_t_by_reason: dict[str, float] = {}


def trigger_incident(reason: str, extra: dict | None = None, force: bool = False) -> dict:
    """Promote the last INCIDENT_WINDOW_SECONDS into incidents/, debounced.

    `force=True` (used by the manual /incident/trigger endpoint) bypasses
    the cooldown -- an explicit human request should always produce an
    incident, auto-detected anomalies should not spam one per tick while a
    condition persists.
    """
    now = time.time()
    if not force:
        with _incident_lock:
            last_t = _last_incident_t_by_reason.get(reason, 0.0)
            if now - last_t < ANOMALY_COOLDOWN_SECONDS:
                return {"skipped": True, "reason": reason, "cooldown_remaining": ANOMALY_COOLDOWN_SECONDS - (now - last_t)}
            _last_incident_t_by_reason[reason] = now

    meta = retention.promote_incident(BUFFER_DIR, INCIDENTS_DIR, reason, INCIDENT_WINDOW_SECONDS, now=now)
    log_event("warn", "incident triggered", reason=reason, incident_id=meta["id"], **(extra or {}))
    try:
        r.publish("mc.blackbox.incident", json.dumps({"id": meta["id"], "reason": reason, "t": now, **(extra or {})}))
    except Exception as exc:
        log_event("warn", "could not publish incident to redis", error=str(exc))
    return meta


# --- recorder thread ------------------------------------------------------

def recorder_loop() -> None:
    last_frame_t = 0.0
    while not _shutdown.is_set():
        loop_start = time.time()
        try:
            pose = robot.get_pose()
            battery = robot.get_battery()
            imu = robot.get_imu()
            record = {
                "t": loop_start,
                "pose": pose.to_dict(),
                "battery": battery.to_dict(),
                "imu": imu.to_dict(),
            }
            retention.append_record(BUFFER_DIR, record)
            with _telemetry_lock:
                _latest["pose"] = pose
                _latest["battery"] = battery
                _latest["imu"] = imu
                _latest["poll_failures"] = 0
                _latest["last_poll_ok_t"] = loop_start
        except Exception as exc:
            with _telemetry_lock:
                _latest["poll_failures"] += 1
                failures = _latest["poll_failures"]
            log_event("error", "telemetry poll failed", error=str(exc), consecutive_failures=failures)

        if loop_start - last_frame_t >= FRAME_INTERVAL_SECONDS:
            try:
                frame = robot.get_camera_frame()
                fname = retention.frame_filename(loop_start)
                with open(os.path.join(retention.frames_dir(BUFFER_DIR), fname), "wb") as f:
                    f.write(frame)
                last_frame_t = loop_start
            except Exception as exc:
                log_event("warn", "frame capture failed", error=str(exc))

        elapsed = time.time() - loop_start
        _shutdown.wait(max(0.0, RECORD_INTERVAL_SECONDS - elapsed))


# --- pruning thread ---------------------------------------------------

def pruning_loop() -> None:
    while not _shutdown.is_set():
        try:
            summary = retention.prune_buffer(BUFFER_DIR, RETENTION_SECONDS, MAX_BUFFER_BYTES)
            if summary["removed_log_lines"] or summary["removed_frames"]:
                log_event("info", "pruned buffer", **summary)
        except Exception as exc:
            log_event("error", "prune failed", error=str(exc))
        _shutdown.wait(PRUNE_INTERVAL_SECONDS)


# --- anomaly detection thread ------------------------------------------

def anomaly_loop() -> None:
    prev_battery_pct = None
    prev_battery_t = None
    prev_imu = None

    while not _shutdown.is_set():
        _shutdown.wait(ANOMALY_CHECK_INTERVAL_SECONDS)
        if _shutdown.is_set():
            break

        with _telemetry_lock:
            battery = _latest["battery"]
            imu = _latest["imu"]
            poll_failures = _latest["poll_failures"]
            last_ok = _latest["last_poll_ok_t"]

        # (c) robot/process seems dead -- repeated poll failures, or no
        # successful poll for way longer than the record interval should
        # ever allow (belt-and-braces vs. the counter above).
        if poll_failures >= POLL_FAILURE_THRESHOLD:
            trigger_incident("robot_unresponsive", extra={"consecutive_failures": poll_failures})
        elif time.time() - last_ok > max(POLL_FAILURE_THRESHOLD * RECORD_INTERVAL_SECONDS, 10.0):
            trigger_incident("polling_stalled", extra={"seconds_since_last_ok": time.time() - last_ok})

        # (a) battery percent dropping faster than threshold
        if battery is not None:
            if prev_battery_pct is not None and prev_battery_t is not None:
                dt = battery.t - prev_battery_t
                if dt > 0:
                    rate = (prev_battery_pct - battery.percent) / dt
                    if rate > BATTERY_DROP_PCT_PER_SEC:
                        trigger_incident("battery_drop", extra={"rate_pct_per_sec": round(rate, 3)})
            prev_battery_pct = battery.percent
            prev_battery_t = battery.t

        # (b) IMU jump between consecutive samples ("impact")
        if imu is not None:
            if prev_imu is not None:
                d_accel = abs(imu.accel_z - prev_imu.accel_z)
                d_roll = abs(imu.roll - prev_imu.roll)
                d_pitch = abs(imu.pitch - prev_imu.pitch)
                if (
                    d_accel > ACCEL_Z_JUMP_THRESHOLD
                    or d_roll > ROLL_PITCH_JUMP_THRESHOLD_RAD
                    or d_pitch > ROLL_PITCH_JUMP_THRESHOLD_RAD
                ):
                    trigger_incident(
                        "impact",
                        extra={
                            "d_accel_z": round(d_accel, 3),
                            "d_roll": round(d_roll, 3),
                            "d_pitch": round(d_pitch, 3),
                        },
                    )
            prev_imu = imu


# --- redis subscriber thread (mc.core.anomaly) --------------------------

def redis_subscribe_loop() -> None:
    while not _shutdown.is_set():
        try:
            pubsub = r.pubsub()
            pubsub.subscribe("mc.core.anomaly")
            log_event("info", "subscribed to mc.core.anomaly")
            for msg in pubsub.listen():
                if _shutdown.is_set():
                    break
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    payload = {"raw": raw}
                reason = str(payload.get("reason", "mc_core_anomaly")) if isinstance(payload, dict) else "mc_core_anomaly"
                trigger_incident(f"external_{reason}", extra={"source": "mc.core.anomaly", "payload": payload})
        except Exception as exc:
            log_event("warn", "redis subscribe loop error, will retry", error=str(exc))
            _shutdown.wait(5.0)


# --- HTTP API -------------------------------------------------------------

class IncidentTriggerRequest(BaseModel):
    reason: str = "manual"


@app.post("/incident/trigger")
def incident_trigger(body: IncidentTriggerRequest):
    meta = trigger_incident(body.reason, extra={"source": "api"}, force=True)
    return meta


@app.get("/incidents")
def incidents_list():
    return {"incidents": retention.list_incidents(INCIDENTS_DIR)}


@app.get("/incidents/{incident_id}")
def incidents_detail(incident_id: str):
    detail = retention.get_incident_detail(INCIDENTS_DIR, incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="incident not found")
    detail["frame_urls"] = [
        f"/incidents_files/{incident_id}/frames/{name}" for name in detail["frames"]
    ]
    return detail


@app.get("/buffer/status")
def buffer_status():
    stats = retention.buffer_stats(BUFFER_DIR)
    return {
        "total_mb": round(stats.total_bytes / (1024 * 1024), 3),
        "log_mb": round(stats.log_bytes / (1024 * 1024), 3),
        "frame_mb": round(stats.frame_bytes / (1024 * 1024), 3),
        "frame_count": stats.frame_count,
        "oldest_ts": stats.oldest_ts,
        "newest_ts": stats.newest_ts,
        "retention_seconds": RETENTION_SECONDS,
        "max_buffer_mb": MAX_BUFFER_MB,
    }


@app.get("/health")
def health():
    return {"ok": True, "pillar": PILLAR}


# --- startup ---------------------------------------------------------

threading.Thread(target=recorder_loop, daemon=True, name="blackbox-recorder").start()
threading.Thread(target=pruning_loop, daemon=True, name="blackbox-pruning").start()
threading.Thread(target=anomaly_loop, daemon=True, name="blackbox-anomaly").start()
threading.Thread(target=redis_subscribe_loop, daemon=True, name="blackbox-redis-sub").start()

log_event("info", "blackbox started", retention_seconds=RETENTION_SECONDS, max_buffer_mb=MAX_BUFFER_MB)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9108)
