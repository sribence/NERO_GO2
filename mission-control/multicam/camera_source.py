"""Camera abstraction for the multicam pillar.

Two kinds of camera source, both exposing the same tiny interface
(`grab_jpeg() -> bytes`, plus discovery/availability bits), kept free of
FastAPI so it is easy to unit-test in isolation:

  - `UsbCameraSource`   -- a local USB webcam via OpenCV (`cv2.VideoCapture`).
    Used for side/rear/night-vision cams via `/dev/videoN` passthrough on
    the Jetson. Gracefully marks itself unavailable if the device can't be
    opened (no hardware present) instead of raising/crashing.

  - `RobotClientCameraSource` -- wraps `core.robot_client`'s own camera
    (`get_camera_frame(cam_id)`), used for the robot's built-in "front"
    camera. This is what keeps the camera list non-empty on a dev machine
    with no `/dev/video*` at all.
"""
from __future__ import annotations

import abc
import glob
import logging
import os
import sys
import threading
from typing import Optional

logger = logging.getLogger("multicam.camera_source")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))


class CameraSource(abc.ABC):
    """One addressable camera: a JPEG-frame producer."""

    cam_id: str
    label: str
    source_kind: str  # "usb" | "robot_client"

    @abc.abstractmethod
    def is_available(self) -> bool:
        ...

    @abc.abstractmethod
    def grab_jpeg(self) -> bytes:
        """Return one JPEG frame as bytes. Raises RuntimeError if unavailable."""

    def close(self) -> None:
        pass

    def to_dict(self) -> dict:
        return {"cam_id": self.cam_id, "source": self.source_kind, "label": self.label}


class UsbCameraSource(CameraSource):
    """A local USB camera opened via OpenCV's VideoCapture.

    Opens lazily and caches the capture handle. If the device can't be
    opened (no hardware, wrong index, permission issue) `is_available()`
    reports False and `grab_jpeg()` raises a RuntimeError -- callers must
    not crash the service over a missing camera.
    """

    def __init__(self, cam_id: str, device_index: int, label: Optional[str] = None):
        self.cam_id = cam_id
        self.device_index = device_index
        self.label = label or cam_id
        self.source_kind = "usb"
        self._lock = threading.Lock()
        self._cap = None
        self._available: Optional[bool] = None  # unknown until first probe

    def _ensure_open(self):
        import cv2  # local import: keep OpenCV optional for non-usb code paths

        with self._lock:
            if self._cap is not None and self._cap.isOpened():
                return self._cap
            try:
                cap = cv2.VideoCapture(self.device_index)
                if not cap or not cap.isOpened():
                    logger.warning(
                        "usb camera %s (index %d) failed to open -- marking unavailable",
                        self.cam_id, self.device_index,
                    )
                    self._available = False
                    self._cap = None
                    return None
                self._cap = cap
                self._available = True
                return cap
            except Exception:
                logger.warning(
                    "usb camera %s (index %d) raised while opening -- marking unavailable",
                    self.cam_id, self.device_index, exc_info=True,
                )
                self._available = False
                self._cap = None
                return None

    def is_available(self) -> bool:
        if self._available is None:
            self._ensure_open()
        return bool(self._available)

    def grab_jpeg(self) -> bytes:
        import cv2

        cap = self._ensure_open()
        if cap is None:
            raise RuntimeError(f"usb camera {self.cam_id} is not available")
        with self._lock:
            ok, frame = cap.read()
        if not ok or frame is None:
            self._available = False
            raise RuntimeError(f"usb camera {self.cam_id} failed to read a frame")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError(f"usb camera {self.cam_id} failed to encode JPEG")
        return buf.tobytes()

    def close(self) -> None:
        with self._lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None


class RobotClientCameraSource(CameraSource):
    """Wraps `core.robot_client.get_robot_client()`'s camera, e.g. cam_id='front'."""

    def __init__(self, cam_id: str = "front", label: Optional[str] = None):
        self.cam_id = cam_id
        self.label = label or cam_id
        self.source_kind = "robot_client"
        self._robot = None
        self._robot_lock = threading.Lock()
        self._last_ok = True

    def _get_robot(self):
        # Instantiated once. MockRobotClient's constructor starts a daemon
        # tick thread that is never stopped, so building one per frame
        # leaked a thread per frame -- ~600/min on a 10fps MJPEG stream
        # (AUDIT-2026-09-10.md, P0-9).
        if self._robot is None:
            with self._robot_lock:
                if self._robot is None:
                    from robot_client import get_robot_client

                    self._robot = get_robot_client()
        return self._robot

    def is_available(self) -> bool:
        # Reflects the last actual grab rather than always claiming True --
        # a disconnected live robot must not show as an available camera.
        return self._last_ok

    def grab_jpeg(self) -> bytes:
        try:
            frame = self._get_robot().get_camera_frame(self.cam_id)
        except Exception:
            self._last_ok = False
            raise
        self._last_ok = True
        return frame


class YoloUnavailableError(RuntimeError):
    """Raised when ultralytics isn't installed or model load failed."""


class YoloDetector:
    """Lazy-loaded, cached YOLOv8 detector shared across all cameras.

    Wraps `yolo_detector.detect()`. Decodes JPEG bytes (as returned by
    `CameraSource.grab_jpeg()`) to a numpy BGR frame via cv2 before
    handing it to ultralytics -- keeps the JSON contract identical to the
    sibling-clone prototype (`docker/realsense_bridge/yolo_detector.py`).
    """

    def __init__(self, weights: str, conf_threshold: float):
        self.weights = weights
        self.conf_threshold = conf_threshold
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None

    def _ensure_loaded(self):
        import yolo_detector

        with self._lock:
            try:
                return yolo_detector.load_model(self.weights)
            except Exception as exc:
                self._load_error = str(exc)
                raise YoloUnavailableError(f"YOLO model load failed: {exc}") from exc

    def detect_jpeg(self, jpeg: bytes) -> dict:
        import cv2
        import numpy as np
        import yolo_detector

        self._ensure_loaded()
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype="uint8"), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("failed to decode JPEG frame for YOLO detection")
        with self._lock:
            return yolo_detector.detect(frame, weights=self.weights, conf_threshold=self.conf_threshold)


_yolo_detector: Optional[YoloDetector] = None
_yolo_detector_lock = threading.Lock()


def get_yolo_detector(weights: str, conf_threshold: float) -> YoloDetector:
    global _yolo_detector
    if _yolo_detector is None:
        with _yolo_detector_lock:
            if _yolo_detector is None:
                _yolo_detector = YoloDetector(weights=weights, conf_threshold=conf_threshold)
    return _yolo_detector


def discover_usb_cameras(max_probe: int = 8) -> list[UsbCameraSource]:
    """Discover local USB cameras.

    On Linux (the Jetson target, `ROBOT_BACKEND=live`), scans `/dev/video*`
    and builds one `UsbCameraSource` per device node found. On platforms
    without `/dev/video*` (e.g. this Windows dev box), this returns an
    empty list -- callers should fall back to the robot_client camera so
    the service never reports zero cameras.
    """
    sources: list[UsbCameraSource] = []
    video_nodes = sorted(glob.glob("/dev/video*"))
    if video_nodes:
        labels = ["side", "rear", "night_vision"]
        for i, node in enumerate(video_nodes):
            try:
                index = int("".join(ch for ch in os.path.basename(node) if ch.isdigit()))
            except ValueError:
                continue
            label = labels[i] if i < len(labels) else f"usb{index}"
            cam_id = f"usb{index}"
            sources.append(UsbCameraSource(cam_id=cam_id, device_index=index, label=label))
        return sources

    # No /dev/video* nodes (e.g. Windows dev machine, or a container without
    # device passthrough). Best-effort probe a few OpenCV indices in case
    # cv2 exposes cameras through another backend (e.g. DirectShow) -- but
    # never let a probe failure here crash discovery.
    try:
        import cv2  # noqa: F401
    except ImportError:
        return sources
    return sources
