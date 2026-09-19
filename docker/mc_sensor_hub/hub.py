"""mc_sensor_hub -- read-only sensor aggregator for the Go2 dock.

Runs on the Jetson, inside a container built from the existing
`nero_go2/web_dashboard` image (the dock has no internet, so nothing new can
be pip-installed; this uses only flask + requests + numpy, which that image
already has).

WHY THIS EXISTS INSTEAD OF mission-control's `core`:
`core` can, by design, command the robot. This service cannot. There is no
DDS import, no SportClient, no velocity path -- the movement endpoints exist
only to answer 403 so a client gets a clear refusal instead of a timeout.
That makes "attached for observation only" a property of the deployed code,
not of a configuration flag someone could flip by accident.

It speaks the same HTTP contract the Go2 Console's live backend already
expects from `core`, plus raw point-cloud endpoints for the 3D viewer.

Upstreams (all already running on the dock):
    :5001  webrtc_bridge   /state /camera.jpg /lidar /lidar_state
    :5003  hesai_bridge    /lidar /health
    :9091  realsense_bridge -- NOT http: a rosbridge WebSocket. The colour
           and depth streams publish sensor_msgs/CompressedImage at 15 Hz,
           which is already JPEG/PNG on the wire, so we subscribe once and
           re-serve the newest frame over plain HTTP.
"""
import base64
import os
import struct
import threading
import time

import numpy as np
import requests
from flask import Flask, Response, jsonify, request

GO2 = os.environ.get("GO2_BRIDGE_URL", "http://127.0.0.1:5001")
HESAI = os.environ.get("HESAI_BRIDGE_URL", "http://127.0.0.1:5003")
REALSENSE_WS_HOST = os.environ.get("REALSENSE_WS_HOST", "127.0.0.1")
REALSENSE_WS_PORT = int(os.environ.get("REALSENSE_WS_PORT", "9091"))
PORT = int(os.environ.get("HUB_PORT", "9101"))

STATE_TTL = float(os.environ.get("STATE_TTL_S", "0.12"))
LIDAR_TTL = float(os.environ.get("LIDAR_TTL_S", "0.20"))
LINK_MAX_AGE_S = float(os.environ.get("LINK_MAX_AGE_S", "2.0"))

app = Flask(__name__)
_t0 = time.time()


# ---------------------------------------------------------------------------
# RealSense over rosbridge
# ---------------------------------------------------------------------------

class RosImageTap:
    """Holds the latest frame of one CompressedImage topic.

    Subscribing once and sharing the result matters here: every extra
    rosbridge subscription costs bandwidth on the dock, and the browser may
    open several viewers of the same stream.
    """

    def __init__(self, topic):
        self.topic = topic
        self.lock = threading.Lock()
        self.frame = None
        self.t = 0.0
        self.error = "nem indult el"
        self.count = 0
        threading.Thread(target=self._run, daemon=True,
                         name=f"ros-{topic.split('/')[2]}").start()

    def _run(self):
        backoff = 2.0
        while True:
            try:
                import roslibpy
                client = roslibpy.Ros(host=REALSENSE_WS_HOST, port=REALSENSE_WS_PORT)
                client.run(timeout=10)
                sub = roslibpy.Topic(client, self.topic, "sensor_msgs/CompressedImage",
                                     queue_length=1, throttle_rate=100)
                sub.subscribe(self._on_msg)
                self.error = None
                backoff = 2.0
                while client.is_connected:
                    time.sleep(1.0)
                self.error = "rosbridge kapcsolat megszakadt"
            except Exception as exc:
                self.error = str(exc)[:160]
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_msg(self, msg):
        try:
            data = base64.b64decode(msg["data"])
        except Exception:
            return
        with self.lock:
            self.frame = data
            self.t = time.time()
            self.count += 1

    def get(self):
        with self.lock:
            return self.frame, self.t, self.error

    def age(self):
        return (time.time() - self.t) if self.t else float("inf")


REALSENSE_TOPICS = {
    "rs_color": "/camera/color/image_raw/compressed",
    "rs_depth": "/camera/depth/image_rect_raw/compressed",
}
taps = {}
if os.environ.get("ENABLE_REALSENSE", "1") == "1":
    taps = {k: RosImageTap(v) for k, v in REALSENSE_TOPICS.items()}


class Cached:
    """One in-flight fetch per upstream, shared by every client."""

    def __init__(self, url, ttl):
        self.url = url
        self.ttl = ttl
        self.lock = threading.Lock()
        self.data = None
        self.t = 0.0
        self.ok_t = 0.0
        self.error = None

    def get(self, timeout=3.0):
        with self.lock:
            if self.data is not None and (time.time() - self.t) < self.ttl:
                return self.data
            try:
                r = requests.get(self.url, timeout=timeout)
                r.raise_for_status()
                self.data = r.json()
                self.t = self.ok_t = time.time()
                self.error = None
            except Exception as exc:
                self.error = str(exc)
                self.t = time.time()
            return self.data

    def age(self):
        return (time.time() - self.ok_t) if self.ok_t else float("inf")


state_c = Cached(f"{GO2}/state", STATE_TTL)
go2_lidar_c = Cached(f"{GO2}/lidar", LIDAR_TTL)
hesai_c = Cached(f"{HESAI}/lidar", LIDAR_TTL)
lidar_state_c = Cached(f"{GO2}/lidar_state", 1.0)


def _decimate(points, limit):
    """Uniformly thin a cloud. Hesai alone is ~500 kB per frame, which no
    browser wants at 10 Hz."""
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] == 0:
        return []
    if limit and arr.shape[0] > limit:
        idx = np.linspace(0, arr.shape[0] - 1, limit).astype(np.int32)
        arr = arr[idx]
    return arr.tolist()


# ---------------------------------------------------------------------------
# Console contract
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"ok": True, "pillar": "mc_sensor_hub", "readonly": True,
                    "uptime_s": round(time.time() - _t0, 1)})


@app.route("/armed")
def armed():
    return jsonify({"armed": False, "readonly": True})


@app.route("/state")
def state():
    s = state_c.get() or {}
    low = s.get("lowstate") or {}
    sms = s.get("sportmodestate")
    bms = low.get("bms_state") or {}
    imu = low.get("imu_state") or {}
    rpy = imu.get("rpy") or [0.0, 0.0, 0.0]

    # sportmodestate only publishes while sport mode is active. Until then
    # there is no position at all -- report it as absent, never as the origin.
    pose = None
    if sms and sms.get("position") is not None:
        p = sms["position"]
        srpy = (sms.get("imu_state") or {}).get("rpy") or [0.0, 0.0, 0.0]
        pose = {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]),
                "yaw": float(srpy[2]), "level_id": "ground", "t": time.time()}

    temps = [m.get("temperature", 0) for m in (low.get("motor_state") or [])
             if m.get("temperature")]
    age = state_c.age()

    return jsonify({
        "readonly": True,
        "pose": pose,
        "pose_available": pose is not None,
        "pose_unavailable_reason": None if pose else
            "sportmodestate nem publikál (a robot nincs sport módban)",
        "battery": {
            "percent": bms.get("soc"),
            "voltage": low.get("power_v"),
            "current": (bms.get("current") or 0) / 1000.0 if bms.get("current") is not None else None,
            "cycles": bms.get("cycle"),
            "t": time.time(),
        },
        "imu": {"roll": rpy[0], "pitch": rpy[1], "yaw": rpy[2],
                "accel_z": 9.81, "t": time.time()},
        "armed": False,
        "mode": "--",
        "motor_temps": temps,
        "max_motor_temp": max(temps) if temps else None,
        "body_temp_c": low.get("temperature_ntc1"),
        "foot_force": low.get("foot_force"),
        "link": {"tracked": True,
                 "healthy": age <= LINK_MAX_AGE_S,
                 "age_s": None if age == float("inf") else round(age, 3),
                 "latency_ms": None,
                 "error": state_c.error},
        "lidar_state": lidar_state_c.get() or {},
        "sources": {
            "go2_camera": state_c.error is None,
            "go2_lidar": go2_lidar_c.error is None,
            "hesai": hesai_c.error is None,
            **{k: (t.error is None and t.age() < 5) for k, t in taps.items()},
        },
        "realsense": {k: {"frames": t.count, "age_s": (None if t.age() == float("inf")
                                                        else round(t.age(), 2)),
                           "error": t.error} for k, t in taps.items()},
        "watchdog_trips": 0,
        "t": time.time(),
    })


@app.route("/lidar_points")
def lidar_points():
    """core-compatible shape, for anything already speaking that contract."""
    pts = _decimate(go2_lidar_c.get() or [], int(request.args.get("max", 4000)))
    return jsonify({"points": [{"x": p[0], "y": p[1], "z": p[2]} for p in pts]})


@app.route("/lidar/<source>")
def lidar_raw(source):
    """Compact [[x,y,z], ...] for the 3D viewer -- half the bytes of the
    dict form, which matters at 500k points."""
    limit = int(request.args.get("max", 6000))
    if source == "go2":
        pts, c = go2_lidar_c.get() or [], go2_lidar_c
    elif source == "hesai":
        pts, c = hesai_c.get() or [], hesai_c
    else:
        return jsonify({"error": f"unknown source {source}"}), 404
    raw_n = len(pts) if isinstance(pts, list) else 0
    out = _decimate(pts, limit)
    return jsonify({"source": source, "points": out,
                    "count": len(out), "raw_count": raw_n,
                    "error": c.error, "t": time.time()})


# Binary point cloud, for the PC-side KISS-ICP SLAM.
#
# The JSON form of one Hesai frame is ~1.2 MB and takes ~190 ms to move off
# the dock, which caps the SLAM at ~2 Hz. The same points as packed float32
# are ~216 kB, and neither side has to parse a number. Route deliberately
# does not live under /lidar/<source>, so it can never shadow it.

_bin_cache = {"t": 0.0, "key": None, "buf": b""}
_bin_lock = threading.Lock()


@app.route("/lidar_bin/<source>")
def lidar_bin(source):
    """magic 'PC3D' + uint32 point count + count * 3 * float32 little-endian."""
    if source == "go2":
        pts = go2_lidar_c.get() or []
    elif source == "hesai":
        pts = hesai_c.get() or []
    else:
        return jsonify({"error": f"unknown source {source}"}), 404
    limit = int(request.args.get("max", 0))

    key = (source, len(pts), limit)
    with _bin_lock:
        if _bin_cache["key"] == key and (time.time() - _bin_cache["t"]) < LIDAR_TTL:
            buf = _bin_cache["buf"]
        else:
            arr = np.asarray(pts, dtype=np.float32)
            if arr.ndim != 2 or arr.shape[0] == 0:
                arr = np.zeros((0, 3), dtype=np.float32)
            else:
                arr = arr[:, :3]
                if limit and arr.shape[0] > limit:
                    idx = np.linspace(0, arr.shape[0] - 1, limit).astype(np.int32)
                    arr = arr[idx]
            arr = np.ascontiguousarray(arr, dtype="<f4")
            buf = b"PC3D" + struct.pack("<I", arr.shape[0]) + arr.tobytes()
            _bin_cache.update(t=time.time(), key=key, buf=buf)
    return Response(buf, mimetype="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


@app.route("/camera_frame")
def camera_frame():
    try:
        r = requests.get(f"{GO2}/camera.jpg", timeout=4)
        r.raise_for_status()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify({"cam_id": request.args.get("cam_id", "front"),
                    "jpeg_b64": base64.b64encode(r.content).decode("ascii")})


@app.route("/camera/<name>.jpg")
def camera_named(name):
    tap = taps.get(name)
    if tap is None:
        return jsonify({"error": f"unknown camera {name}"}), 404
    frame, _t, err = tap.get()
    if frame is None:
        return jsonify({"error": err or "még nincs képkocka"}), 503
    return Response(frame, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.route("/cameras")
def cameras():
    out = [{"cam_id": "front", "label": "Go2 orr-kamera", "source": "webrtc",
            "available": state_c.error is None}]
    labels = {"rs_color": "RealSense szín", "rs_depth": "RealSense mélység"}
    for k, tap in taps.items():
        out.append({"cam_id": k, "label": labels.get(k, k), "source": "realsense",
                    "available": tap.get()[0] is not None and tap.age() < 5})
    return jsonify(out)


@app.route("/camera.jpg")
def camera_jpg():
    try:
        r = requests.get(f"{GO2}/camera.jpg", timeout=4)
        r.raise_for_status()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503
    return Response(r.content, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Movement: present only to refuse clearly
# ---------------------------------------------------------------------------

@app.route("/move", methods=["POST"])
@app.route("/arm", methods=["POST"])
@app.route("/disarm", methods=["POST"])
@app.route("/stop", methods=["POST"])
@app.route("/estop", methods=["POST"])
def refuse():
    return jsonify({
        "error": "read-only sensor hub",
        "detail": "Ez a szolgáltatás nem tud robotot mozgatni: nincs benne "
                  "DDS/SportClient kódút. Mozgatáshoz a mission-control core "
                  "kell, külön, tudatos telepítéssel.",
    }), 403


if __name__ == "__main__":
    print(f"[mc_sensor_hub] READ-ONLY, port {PORT}, go2={GO2} hesai={HESAI}", flush=True)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
