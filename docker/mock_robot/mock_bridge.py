"""
Mock stand-in for `webrtc_bridge` — same HTTP API, synthetic data.

Why this exists: the real Go2 is a single, expensive, physically-shared
piece of hardware (ld. docs/00-BIZTONSAGI-SZABALYOK.md) — the web_dashboard
UI/UX (joystick feel, layout, telemetry panels) shouldn't have to wait for
robot access to be iterated on. Point WEBRTC_BRIDGE_URL at this instead of
the real bridge and the dashboard behaves identically from the frontend's
point of view, with plausible-looking fake data instead of the real feed.

Endpoint parity with docker/webrtc_bridge/bridge.py: /health, /camera.jpg,
/lidar, /lidar_state, /state — same shapes, so web_dashboard/app.py needs
zero changes to work against this.
"""

import io
import math
import time

from flask import Flask, Response, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

_START = time.time()


def _t():
    return time.time() - _START


@app.route("/health")
def health():
    return jsonify({"status": "ok", "connected": True})


@app.route("/camera.jpg")
def camera_jpeg():
    # A synthetic "camera view": moving horizon + a bouncing marker, plus
    # a timestamp so you can see the feed is actually live/updating.
    w, h = 640, 480
    img = Image.new("RGB", (w, h), (60, 90, 110))
    draw = ImageDraw.Draw(img)
    horizon_y = h // 2 + int(20 * math.sin(_t() * 0.5))
    draw.rectangle([0, horizon_y, w, h], fill=(70, 60, 50))
    bx = int(w / 2 + (w / 2 - 40) * math.sin(_t() * 0.8))
    by = horizon_y - 30
    draw.ellipse([bx - 20, by - 20, bx + 20, by + 20], fill=(220, 80, 60))
    draw.text((10, 10), f"MOCK CAMERA  t={_t():.1f}s", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return Response(buf.getvalue(), mimetype="image/jpeg")


@app.route("/lidar")
def lidar():
    # A small synthetic "room": a ring of points around the origin plus
    # some noise, cheap to generate, good enough to exercise a 3D viewer.
    points = []
    n = 720
    for i in range(n):
        angle = (i / n) * 2 * math.pi
        r = 2.5 + 0.4 * math.sin(angle * 3 + _t())
        points.append([r * math.cos(angle), r * math.sin(angle), 0.05 * math.sin(angle * 5)])
    return jsonify(points)


@app.route("/lidar_state")
def lidar_state():
    return jsonify(
        {
            "cloud_frequency": 15.0,
            "cloud_scan_num": int(_t() * 15) % 10000,
            "cloud_size": 56000,
            "com_rotation_speed": 260.0,
            "dirty_percentage": 5,
            "error_state": 0,
            "software_version": "mock-1.0.0",
        }
    )


@app.route("/state")
def state():
    t = _t()
    return jsonify(
        {
            "lowstate": {
                "imu_state": {"rpy": [0.02 * math.sin(t), 0.01 * math.cos(t), 0.0]},
                "bms_state": {"soc": max(0, 80 - int(t / 30))},
                "temperature_ntc1": 35,
                "power_v": round(28.5 - 0.05 * math.sin(t * 0.2), 2),
                "power_a": round(1.0 + 0.3 * math.sin(t), 2),
            },
            "sportmodestate": {
                "velocity": [0.2 * math.sin(t * 0.5), 0.0, 0.0],
                "yaw_speed": round(0.1 * math.sin(t * 0.3), 3),
            },
            "wireless_controller": None,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
