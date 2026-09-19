"""Audio pillar — event-reactive sound playback (port 9107).

Per CONVENTIONS.md: JSONL logs to logs/events.jsonl, subscribes to the
Redis channel `mc.core.proximity_alert` and auto-triggers the
`proximity_warning` sound (with a cooldown). Playback runs headless-safe:
tries a real backend (simpleaudio, falling back to `aplay`) but always
succeeds at the HTTP-level and reports what actually happened.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

from fastapi import FastAPI
import uvicorn

# --------------------------------------------------------------------------- config

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
PROXIMITY_CHANNEL = "mc.core.proximity_alert"
PROXIMITY_COOLDOWN_S = float(os.environ.get("PROXIMITY_COOLDOWN_S", "5"))

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")

# event_name -> wav filename. Unknown events fall back to DEFAULT_SOUND.
SOUND_LIBRARY = {
    "proximity_warning": "proximity_warning.wav",
    "task_complete": "task_complete.wav",
    "test": "test.wav",
}
DEFAULT_SOUND = "test.wav"

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "events.jsonl")
_log_lock = threading.Lock()


def log_event(level: str, msg: str, **extra) -> None:
    record = {"t": time.time(), "pillar": "audio", "level": level, "msg": msg}
    record.update(extra)
    line = json.dumps(record, default=str)
    with _log_lock:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    print(line, flush=True)


# --------------------------------------------------------------------------- playback backends

def _try_simpleaudio(path: str) -> bool:
    # Run in a throwaway subprocess rather than importing simpleaudio in-process:
    # on some hosts (observed on Windows dev/no real output device, and
    # plausible in a headless container with a broken ALSA stack)
    # simpleaudio's native playback call can segfault the whole process
    # instead of raising a catchable Python exception. Isolating it means a
    # bad host only loses this one playback attempt, not the whole service.
    try:
        import sys

        code = (
            "import sys\n"
            "import simpleaudio as sa\n"
            "sa.WaveObject.from_wave_file(sys.argv[1]).play().wait_done()\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", code, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Give it a brief moment to fail fast (e.g. simpleaudio not
        # installed, no output device) so we can fall back to aplay;
        # otherwise treat it as a successful hand-off and let it finish
        # playing in the background.
        try:
            returncode = proc.wait(timeout=0.3)
            return returncode == 0
        except subprocess.TimeoutExpired:
            return True
    except Exception:
        return False


def _try_aplay(path: str) -> bool:
    aplay = shutil.which("aplay")
    if not aplay:
        return False
    try:
        subprocess.Popen(
            [aplay, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except Exception:
        return False


def play_file(path: str) -> tuple[bool, str]:
    """Attempt playback via available backends. Returns (played, backend_used)."""
    if _try_simpleaudio(path):
        return True, "simpleaudio"
    if _try_aplay(path):
        return True, "aplay"
    return False, "none"


# --------------------------------------------------------------------------- play logic

def play_event(event_name: str) -> dict:
    filename = SOUND_LIBRARY.get(event_name, DEFAULT_SOUND)
    path = os.path.join(SOUNDS_DIR, filename)
    exists = os.path.isfile(path)

    played, backend = (False, "none")
    if exists:
        played, backend = play_file(path)

    result = {
        "played": played,
        "backend": backend,
        "file": filename,
        "event": event_name,
        "fallback_used": event_name not in SOUND_LIBRARY,
        "file_found": exists,
    }
    log_event(
        "info" if exists else "warn",
        f"play event '{event_name}' -> {filename} (played={played}, backend={backend})",
        **result,
    )
    return result


# --------------------------------------------------------------------------- redis subscriber

_last_proximity_trigger = 0.0
_proximity_lock = threading.Lock()


def _handle_proximity_alert(raw_payload: str) -> None:
    global _last_proximity_trigger
    now = time.time()
    with _proximity_lock:
        if now - _last_proximity_trigger < PROXIMITY_COOLDOWN_S:
            return
        _last_proximity_trigger = now
    log_event("info", "proximity_alert received, triggering proximity_warning", raw=raw_payload)
    play_event("proximity_warning")


def _redis_subscriber_loop():
    try:
        import redis as redis_lib
    except ImportError:
        log_event("warn", "redis package not installed, proximity subscriber disabled")
        return

    backoff = 2.0
    while True:
        try:
            client = redis_lib.Redis(
                host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2
            )
            client.ping()
            log_event("info", f"redis subscriber connected at {REDIS_HOST}:{REDIS_PORT}")
            pubsub = client.pubsub()
            pubsub.subscribe(PROXIMITY_CHANNEL)
            backoff = 2.0
            for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                _handle_proximity_alert(msg.get("data"))
        except Exception as exc:  # noqa: BLE001
            log_event("warn", f"redis subscriber lost/unavailable, retrying in {backoff:.0f}s: {exc}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


threading.Thread(target=_redis_subscriber_loop, daemon=True).start()

# --------------------------------------------------------------------------- fastapi

app = FastAPI(title="mission-control: audio")


@app.on_event("startup")
async def _on_startup():
    log_event("info", "audio service starting", port=9107)


@app.post("/audio/play/{event_name}")
def play(event_name: str):
    return play_event(event_name)


@app.get("/audio/library")
def library():
    return {
        "events": SOUND_LIBRARY,
        "default": DEFAULT_SOUND,
        "sounds_dir": SOUNDS_DIR,
        "available_files": sorted(os.listdir(SOUNDS_DIR)) if os.path.isdir(SOUNDS_DIR) else [],
    }


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9107)
