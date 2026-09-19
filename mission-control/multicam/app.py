"""mission-control: multicam pillar (port 9106).

Pluggable multi-USB-camera manager: the robot's built-in "front" camera
(via `core.robot_client`) plus N additional USB cameras (side/rear/
night-vision on the Jetson via `/dev/video*` passthrough).

Endpoints:
    GET  /cameras                         -- discover available cameras
    GET  /cameras/{cam_id}/frame          -- one JPEG frame
    GET  /cameras/{cam_id}/stream         -- MJPEG live stream
    POST /cameras/{cam_id}/record/start   -- start continuous frame-saving
    POST /cameras/{cam_id}/record/stop    -- stop it
    GET  /cameras/{cam_id}/detections     -- one-shot YOLOv8 detection (JSON)
    GET  /                                -- HTML page with <img> tags per camera

Talks to the robot only through `core/robot_client.py`, per CONVENTIONS.md.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import uvicorn

from camera_source import (
    CameraSource,
    RobotClientCameraSource,
    YoloUnavailableError,
    discover_usb_cameras,
    get_yolo_detector,
)

PILLAR = "multicam"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
LOG_PATH = os.path.join(LOGS_DIR, "events.jsonl")
RECORD_FPS = float(os.environ.get("RECORD_FPS", "2"))
MJPEG_BOUNDARY = "mjpegboundary"
YOLO_WEIGHTS = os.environ.get("YOLO_WEIGHTS", "yolov8n.pt")
YOLO_CONF = float(os.environ.get("YOLO_CONF", "0.4"))

os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

app = FastAPI(title="mission-control: multicam")


def log_event(level: str, msg: str, **extra) -> None:
    record = {"t": time.time(), "pillar": PILLAR, "level": level, "msg": msg, **extra}
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Camera registry
# ---------------------------------------------------------------------------

_cameras: dict[str, CameraSource] = {}
_cameras_lock = threading.Lock()


def _build_registry() -> dict[str, CameraSource]:
    registry: dict[str, CameraSource] = {}

    # The robot's own front camera is always registered so the endpoint
    # list is never empty on a dev machine with no USB cameras / no
    # /dev/video* at all.
    front = RobotClientCameraSource(cam_id="front", label="front")
    registry[front.cam_id] = front

    for usb_cam in discover_usb_cameras():
        registry[usb_cam.cam_id] = usb_cam

    return registry


def get_registry() -> dict[str, CameraSource]:
    with _cameras_lock:
        if not _cameras:
            _cameras.update(_build_registry())
        return dict(_cameras)


def get_camera(cam_id: str) -> CameraSource:
    registry = get_registry()
    cam = registry.get(cam_id)
    if cam is None:
        raise HTTPException(status_code=404, detail=f"unknown cam_id: {cam_id}")
    return cam


# ---------------------------------------------------------------------------
# Recording state (one background thread per actively-recording camera)
# ---------------------------------------------------------------------------

class RecordingSession:
    def __init__(self, cam_id: str, out_dir: str, fps: float):
        self.cam_id = cam_id
        self.out_dir = out_dir
        self.fps = max(0.1, fps)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.frame_count = 0

    def start(self, cam: CameraSource) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        self._thread = threading.Thread(target=self._run, args=(cam,), daemon=True)
        self._thread.start()

    def _run(self, cam: CameraSource) -> None:
        period = 1.0 / self.fps
        idx = 0
        while not self._stop_event.is_set():
            start = time.time()
            try:
                jpeg = cam.grab_jpeg()
                path = os.path.join(self.out_dir, f"frame_{idx:06d}.jpg")
                with open(path, "wb") as f:
                    f.write(jpeg)
                idx += 1
                self.frame_count = idx
            except Exception as exc:
                log_event("warn", "recording frame grab failed", cam_id=self.cam_id, error=str(exc))
            elapsed = time.time() - start
            self._stop_event.wait(max(0.0, period - elapsed))

    def stop(self) -> int:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return self.frame_count


_recordings: dict[str, RecordingSession] = {}
_recordings_lock = threading.Lock()


# ---------------------------------------------------------------------------
# GET /cameras
# ---------------------------------------------------------------------------

@app.get("/cameras")
def list_cameras():
    registry = get_registry()
    result = []
    for cam in registry.values():
        entry = cam.to_dict()
        entry["available"] = cam.is_available()
        result.append(entry)
    log_event("info", "cameras listed", count=len(result))
    return result


# ---------------------------------------------------------------------------
# GET /cameras/{cam_id}/frame
# ---------------------------------------------------------------------------

@app.get("/cameras/{cam_id}/frame")
def get_frame(cam_id: str):
    cam = get_camera(cam_id)
    try:
        jpeg = cam.grab_jpeg()
    except Exception as exc:
        log_event("error", "frame grab failed", cam_id=cam_id, error=str(exc))
        raise HTTPException(status_code=503, detail=f"camera {cam_id} unavailable: {exc}") from exc
    log_event("info", "frame served", cam_id=cam_id, bytes=len(jpeg))
    return Response(content=jpeg, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# GET /cameras/{cam_id}/stream  (MJPEG)
# ---------------------------------------------------------------------------

def _mjpeg_generator(cam: CameraSource, fps: float = 10.0):
    period = 1.0 / fps
    while True:
        start = time.time()
        try:
            jpeg = cam.grab_jpeg()
        except Exception as exc:
            log_event("warn", "stream frame grab failed", cam_id=cam.cam_id, error=str(exc))
            time.sleep(0.5)
            continue
        yield (
            b"--" + MJPEG_BOUNDARY.encode() + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
            + jpeg + b"\r\n"
        )
        elapsed = time.time() - start
        time.sleep(max(0.0, period - elapsed))


@app.get("/cameras/{cam_id}/stream")
def stream_camera(cam_id: str):
    cam = get_camera(cam_id)
    if not cam.is_available():
        raise HTTPException(status_code=503, detail=f"camera {cam_id} unavailable")
    log_event("info", "stream started", cam_id=cam_id)
    return StreamingResponse(
        _mjpeg_generator(cam),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
    )


# ---------------------------------------------------------------------------
# POST /cameras/{cam_id}/record/start | /record/stop
# ---------------------------------------------------------------------------

@app.post("/cameras/{cam_id}/record/start")
def record_start(cam_id: str):
    cam = get_camera(cam_id)
    if not cam.is_available():
        raise HTTPException(status_code=503, detail=f"camera {cam_id} unavailable")

    with _recordings_lock:
        if cam_id in _recordings:
            raise HTTPException(status_code=409, detail=f"camera {cam_id} is already recording")
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        out_dir = os.path.join(RECORDINGS_DIR, cam_id, ts)
        session = RecordingSession(cam_id=cam_id, out_dir=out_dir, fps=RECORD_FPS)
        session.start(cam)
        _recordings[cam_id] = session

    log_event("info", "recording started", cam_id=cam_id, out_dir=out_dir, fps=RECORD_FPS)
    return {"cam_id": cam_id, "recording": True, "out_dir": out_dir, "fps": RECORD_FPS}


@app.post("/cameras/{cam_id}/record/stop")
def record_stop(cam_id: str):
    with _recordings_lock:
        session = _recordings.pop(cam_id, None)
    if session is None:
        raise HTTPException(status_code=409, detail=f"camera {cam_id} is not recording")

    frame_count = session.stop()
    log_event("info", "recording stopped", cam_id=cam_id, out_dir=session.out_dir, frame_count=frame_count)
    return {"cam_id": cam_id, "recording": False, "out_dir": session.out_dir, "frame_count": frame_count}


# ---------------------------------------------------------------------------
# GET /cameras/{cam_id}/detections  (YOLOv8, one-shot on current frame)
# ---------------------------------------------------------------------------

@app.get("/cameras/{cam_id}/detections")
def get_detections(cam_id: str):
    cam = get_camera(cam_id)
    try:
        jpeg = cam.grab_jpeg()
    except Exception as exc:
        log_event("error", "frame grab failed for detection", cam_id=cam_id, error=str(exc))
        raise HTTPException(status_code=503, detail=f"camera {cam_id} unavailable: {exc}") from exc

    detector = get_yolo_detector(weights=YOLO_WEIGHTS, conf_threshold=YOLO_CONF)
    try:
        result = detector.detect_jpeg(jpeg)
    except YoloUnavailableError as exc:
        log_event("error", "YOLO unavailable", cam_id=cam_id, error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_event("error", "YOLO detection failed", cam_id=cam_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"detection failed: {exc}") from exc

    log_event("info", "detections served", cam_id=cam_id, count=result["count"], elapsed_ms=result["elapsed_ms"])
    return {"cam_id": cam_id, **result}


# ---------------------------------------------------------------------------
# GET /  -- manual live-view page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    registry = get_registry()
    cards = []
    for cam in registry.values():
        available = cam.is_available()
        status = "available" if available else "unavailable"
        img = (
            f'<img src="/cameras/{cam.cam_id}/stream" alt="{cam.cam_id}" />'
            if available
            else '<div class="offline">no signal</div>'
        )
        cards.append(
            f"""
            <div class="cam-card">
              <h2>{cam.label} <span class="tag">{cam.source_kind}</span></h2>
              <div class="status">{status}</div>
              {img}
            </div>
            """
        )
    body = "\n".join(cards) if cards else "<p>No cameras discovered.</p>"
    html = f"""
    <html>
      <head>
        <title>mission-control: multicam</title>
        <style>
          body {{ font-family: sans-serif; background: #111; color: #eee; margin: 1.5rem; }}
          .grid {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
          .cam-card {{ border: 1px solid #333; border-radius: 8px; padding: 0.75rem; width: 340px; }}
          .cam-card img {{ width: 100%; border-radius: 4px; background: #000; }}
          .tag {{ font-size: 0.75rem; color: #888; }}
          .status {{ font-size: 0.85rem; color: #6f6; margin-bottom: 0.5rem; }}
          .offline {{ width: 100%; height: 200px; display: flex; align-items: center;
                       justify-content: center; background: #000; color: #666; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>multicam live view</h1>
        <div class="grid">{body}</div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9106)
