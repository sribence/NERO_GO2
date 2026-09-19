"""YOLOv8 object detection for the multicam pillar.

Same JSON contract as the sibling-clone prototype
(`C:\\Users\\user\\NERO_GO2\\docker\\realsense_bridge\\yolo_detector.py`):
{"detections": [...], "count": int, "elapsed_ms": float}, each detection
{"class", "class_id", "confidence", "bbox": {x1,y1,x2,y2}}.

Accepts a file path OR a numpy ndarray (BGR frame from cv2.imdecode).
Model is loaded lazily and cached per weights file -- do not construct
YOLO() per frame (multi-second load cost).
"""
from __future__ import annotations

import time

_model_cache: dict[str, object] = {}


def load_model(weights: str = "yolov8n.pt"):
    if weights not in _model_cache:
        from ultralytics import YOLO

        _model_cache[weights] = YOLO(weights)
    return _model_cache[weights]


def detect(image, weights: str = "yolov8n.pt", conf_threshold: float = 0.4) -> dict:
    model = load_model(weights)

    t0 = time.time()
    results = model.predict(source=image, conf=conf_threshold, verbose=False)
    elapsed_ms = (time.time() - t0) * 1000.0

    detections = []
    for result in results:
        names = result.names
        for box in result.boxes:
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
            cls_id = int(box.cls[0])
            detections.append({
                "class": names[cls_id],
                "class_id": cls_id,
                "confidence": round(float(box.conf[0]), 3),
                "bbox": {"x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1)},
            })

    return {
        "detections": detections,
        "count": len(detections),
        "elapsed_ms": round(elapsed_ms, 1),
    }
