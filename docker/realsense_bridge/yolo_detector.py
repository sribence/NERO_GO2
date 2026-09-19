"""
NERO GO2 — YOLOv8 objektumdetektalas. Kepbemenet: fajl-utvonal vagy numpy
ndarray (RealSense/webcam frame). Kimenet: tiszta JSON, agenseknek szant
formaban (bbox, class, confidence).
Fuggoseg: pip install ultralytics
"""

import argparse
import json
import sys
import time

from ultralytics import YOLO

_model_cache = {}


def load_model(weights="yolov8n.pt"):
    if weights not in _model_cache:
        _model_cache[weights] = YOLO(weights)
    return _model_cache[weights]


def detect(image, weights="yolov8n.pt", conf_threshold=0.4):
    """image: fajl-utvonal (str) vagy numpy ndarray (BGR/RGB frame).
    Visszaad egy dict-et: {"detections": [...], "count": int, "elapsed_ms": float}"""
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


def main():
    parser = argparse.ArgumentParser(description="NERO GO2 YOLO detector teszt")
    parser.add_argument("image", help="teszt kep fajl-utvonala")
    parser.add_argument("--weights", default="yolov8n.pt")
    parser.add_argument("--conf", type=float, default=0.4)
    args = parser.parse_args()

    result = detect(args.image, weights=args.weights, conf_threshold=args.conf)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
