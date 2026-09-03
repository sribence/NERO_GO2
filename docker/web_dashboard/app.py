"""
NERO_GO2 web control dashboard.

Architectural pattern (joystick/action UX, DDS client usage) adapted from
go2_dashboard by bentheperson1 (https://github.com/bentheperson1/go2_dashboard,
MIT licence) — this is a fresh implementation, not a copy, and split into two
services (this one is UI + movement control; camera/lidar/webrtc telemetry
live in the separate `webrtc_bridge` service, ld. ../webrtc_bridge/).

Why two services: the robot allows only ONE WebRTC client at a time. This
service never opens its own WebRTC connection - it proxies camera/lidar/health
from `webrtc_bridge`'s HTTP API. Movement control and low-level telemetry use
`unitree_sdk2py`'s native CycloneDDS channel instead, which is a completely
separate transport and does not conflict with WebRTC.

SAFETY: movement (joystick, action buttons) is gated behind a server-side
"armed" flag, default False, auto-disarmed after 30s of inactivity. This
exists because an unintended movement command on real hardware is a real
safety/damage risk - ld. ../../docs/00-BIZTONSAGI-SZABALYOK.md.

Generated with help from a local qwen2.5-coder:14b model, then substantially
rewritten by hand (the model's first draft had a non-functional joystick
frontend, several scoping bugs, and an invented SDK method) — ld.
../../docs/13-lokalis-llm-delegalas.md for what was wrong and why.
"""

import json
import logging
import math
import os
import threading
import time

import requests
from flask import Flask, Response, jsonify, render_template, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nero_go2.web_dashboard")

app = Flask(__name__)

WEBRTC_BRIDGE_URL = os.environ.get("WEBRTC_BRIDGE_URL", "http://localhost:5001")

MOVE_SPEED = 0.5
TURN_SPEED = 1.0
ARM_TIMEOUT_S = 30

# Motor index order for LowState_.motor_state[0..11] — standard Unitree Go2
# convention (FR, FL, RR, RL, each hip/thigh/calf). Used by the /showcase
# 3D view to know which array slot drives which leg joint.
MOTOR_NAMES = [
    "FR_hip", "FR_thigh", "FR_calf",
    "FL_hip", "FL_thigh", "FL_calf",
    "RR_hip", "RR_thigh", "RR_calf",
    "RL_hip", "RL_thigh", "RL_calf",
]

# --- shared state ---
_lock = threading.Lock()
dog_data = {
    "voltage": None,
    "current": None,
    "avg_temp": None,
    "velocity_x": None,
    "velocity_y": None,
    "velocity_z": None,
    "yaw_speed": None,
    "motor_q": [0.0] * 12,
    "motor_tau": [0.0] * 12,
    "motor_temp": [0] * 12,
    "roll": None,
    "pitch": None,
    "yaw": None,
    "mode_label": "—",
}
_armed = False
_last_activity = time.time()
_move_state = {"x": 0.0, "y": 0.0, "yaw": 0.0}

sdk_ready = False
sport_client = None


def _touch_activity():
    global _last_activity
    with _lock:
        _last_activity = time.time()


def _is_armed():
    with _lock:
        return _armed


def _set_armed(value: bool):
    global _armed
    with _lock:
        _armed = value
    if value:
        _touch_activity()


def _watchdog():
    """Auto-disarm after ARM_TIMEOUT_S seconds without joystick/action activity."""
    while True:
        time.sleep(1)
        with _lock:
            idle = _armed and (time.time() - _last_activity) > ARM_TIMEOUT_S
        if idle:
            logger.info("no activity for %ss, auto-disarming", ARM_TIMEOUT_S)
            _set_armed(False)


threading.Thread(target=_watchdog, daemon=True).start()


class _FakeSportClient:
    """Stand-in for unitree_sdk2py's SportClient when MOCK_SDK=1 — logs what
    would have been sent instead of touching real hardware. Method names
    match the real SportClient 1:1 (verified against the official source,
    ld. docstring below), so app.py's _actions()/update_joystick() need no
    branching at all."""

    def _log(self, name, *args):
        logger.info("[MOCK SportClient] %s%s", name, args)

    def Move(self, vx, vy, vyaw):
        self._log("Move", vx, vy, vyaw)

    def RecoveryStand(self):
        self._log("RecoveryStand")

    def StandDown(self):
        self._log("StandDown")

    def Hello(self):
        self._log("Hello")

    def Heart(self):
        self._log("Heart")

    def Sit(self):
        self._log("Sit")


# Neutral standing pose (hip, thigh, calf), radians — well inside every
# joint's real URDF limit (ld. docs/14-capability-showcase-projekt.md),
# same value for all four legs; per-leg sign flips happen in _gait_pose().
_STAND_HIP, _STAND_THIGH, _STAND_CALF = 0.0, 0.8, -1.5

# Which of the 4 legs (in MOTOR_NAMES order: FR, FL, RR, RL) swings forward
# together in a trot — diagonal pairs move in phase, the other two in
# anti-phase, which is what actually makes it read as "walking" and not
# just "wobbling in place".
_TROT_PHASE = [0.0, math.pi, math.pi, 0.0]  # FR, FL, RR, RL


def _gait_pose(t, walking: bool):
    """Returns a flat 12-element joint-angle list (MOTOR_NAMES order) for
    time t. Stand: fixed neutral pose. Walk: a simple sinusoidal trot —
    not motion-captured, just enough to visibly animate all 12 joints for
    a long-running showcase demo."""
    q = []
    for leg_i, phase in enumerate(_TROT_PHASE):
        if walking:
            swing = math.sin(t * 4.0 + phase)
            hip = _STAND_HIP + 0.05 * math.sin(t * 4.0 + phase + math.pi / 2)
            thigh = _STAND_THIGH + 0.35 * swing
            calf = _STAND_CALF - 0.25 * max(swing, 0.0)
        else:
            hip, thigh, calf = _STAND_HIP, _STAND_THIGH, _STAND_CALF
        q.extend([hip, thigh, calf])
    return q


def _init_mock_sdk():
    """MOCK_SDK=1 path — no unitree_sdk2py, no DDS, no real robot. Fills
    dog_data with plausible oscillating values (including a 12-joint gait
    cycle for the /showcase 3D view) on a timer, so the dashboard has
    something to show while developing the UI away from the robot (ld.
    docs/00-BIZTONSAGI-SZABALYOK.md — the robot is expensive/fragile/shared,
    so UI work should not require robot access)."""
    global sdk_ready, sport_client
    sport_client = _FakeSportClient()
    sdk_ready = True
    logger.info("MOCK SportClient ready (MOCK_SDK=1, no real robot involved)")
    t0 = time.time()
    # Repeating demo choreography so a long showcase session (45-90+ min)
    # never looks frozen: stand -> walk -> stand -> ...
    CYCLE_S = 12.0
    while True:
        t = time.time() - t0
        walking = (t % CYCLE_S) > (CYCLE_S * 0.4)
        q = _gait_pose(t, walking)
        with _lock:
            dog_data["voltage"] = round(28.5 - 0.05 * math.sin(t * 0.2), 2)
            dog_data["current"] = round(1.0 + 0.3 * math.sin(t), 2)
            dog_data["avg_temp"] = round(35 + 2 * math.sin(t * 0.1), 1)
            dog_data["velocity_x"] = round(0.6 * math.sin(t * 0.5), 2) if walking else 0.0
            dog_data["velocity_y"] = 0.0
            dog_data["velocity_z"] = 0.0
            dog_data["yaw_speed"] = round(0.1 * math.sin(t * 0.3), 3)
            dog_data["roll"] = round(0.03 * math.sin(t * 4.0), 3) if walking else 0.0
            dog_data["pitch"] = round(0.02 * math.cos(t * 4.0), 3) if walking else 0.0
            dog_data["yaw"] = round(0.05 * math.sin(t * 0.1), 3)
            dog_data["motor_q"] = q
            dog_data["motor_tau"] = [
                round(3.0 + 4.0 * abs(math.sin(t * 4.0 + i)), 2) if walking else round(1.5 + 0.5 * math.sin(t + i), 2)
                for i in range(12)
            ]
            dog_data["motor_temp"] = [round(32 + 6 * (i % 3) + 2 * math.sin(t * 0.05 + i)) for i in range(12)]
            dog_data["mode_label"] = "Járás" if walking else "Állás"
        time.sleep(0.05)


def _init_sdk():
    """Connect to the robot's native DDS channel. Runs in a background thread
    so a robot that isn't reachable yet doesn't prevent the web server (and
    the camera/telemetry proxy routes, which don't need this) from starting.

    2026-09-01: API verified against the official unitreerobotics/
    unitree_sdk2_python source (examples + IDL dataclasses via `gh api`) —
    the previous version used several invented names (`IDLDataClass`,
    `DDSChannelFactoryInitialize`, `create_standard_sdk`, `sdk.create_robot`,
    `communicator.ChannelSubscriber`) that don't exist in the real package.
    """
    global sdk_ready, sport_client
    try:
        from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_
        from unitree_sdk2py.go2.sport.sport_client import SportClient

        def low_state_handler(msg: LowState_):
            with _lock:
                dog_data["voltage"] = round(msg.power_v, 2)
                dog_data["current"] = round(msg.power_a, 2)
                dog_data["avg_temp"] = round((msg.temperature_ntc1 + msg.temperature_ntc2) / 2, 1)
                # 12-elemű tömbök a /showcase 3D nézetéhez, MOTOR_NAMES sorrendben
                # (FR, FL, RR, RL, egyenként hip/thigh/calf).
                dog_data["motor_q"] = [round(m.q, 4) for m in msg.motor_state[:12]]
                dog_data["motor_tau"] = [round(m.tau_est, 2) for m in msg.motor_state[:12]]
                dog_data["motor_temp"] = [m.temperature for m in msg.motor_state[:12]]
                dog_data["roll"] = round(msg.imu_state.rpy[0], 3)
                dog_data["pitch"] = round(msg.imu_state.rpy[1], 3)
                dog_data["yaw"] = round(msg.imu_state.rpy[2], 3)

        def sport_state_handler(msg: SportModeState_):
            with _lock:
                dog_data["velocity_x"] = round(msg.velocity[0], 2)
                dog_data["velocity_y"] = round(msg.velocity[1], 2)
                dog_data["velocity_z"] = round(msg.velocity[2], 2)
                dog_data["yaw_speed"] = round(msg.yaw_speed, 2)

        # domainId=0 (matches the robot's own rt/... topics), network
        # interface name is the Jetson's real NIC (ld. docs/01-halozat.md).
        ChannelFactoryInitialize(0, os.environ.get("DDS_NETWORK_INTERFACE", "eth10"))

        low_state_sub = ChannelSubscriber("rt/lowstate", LowState_)
        low_state_sub.Init(low_state_handler, 10)
        sport_state_sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
        sport_state_sub.Init(sport_state_handler, 10)

        client = SportClient()
        client.SetTimeout(3.0)
        client.Init()

        sport_client = client
        sdk_ready = True
        logger.info("DDS/SportClient ready")
    except Exception:
        logger.exception("failed to initialise unitree_sdk2py DDS connection - movement/telemetry disabled")


threading.Thread(
    target=_init_mock_sdk if os.environ.get("MOCK_SDK") == "1" else _init_sdk,
    daemon=True,
).start()


def _actions():
    if not sport_client:
        return {}
    return {
        "stand_up": sport_client.RecoveryStand,
        "lay_down": sport_client.StandDown,
        "wave": sport_client.Hello,
        "heart": sport_client.Heart,
        "sit": sport_client.Sit,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/showcase")
def showcase():
    return render_template("showcase.html")


@app.route("/showcase_data")
def showcase_data():
    """Dedicated high-frequency SSE stream for the /showcase 3D view — kept
    separate from /data (1 Hz, hits webrtc_bridge/health every tick) so the
    joint animation can update at ~10 Hz without hammering that proxy call."""

    def generate():
        while True:
            with _lock:
                payload = {
                    "motor_q": dog_data["motor_q"],
                    "motor_tau": dog_data["motor_tau"],
                    "motor_temp": dog_data["motor_temp"],
                    "roll": dog_data["roll"],
                    "pitch": dog_data["pitch"],
                    "yaw": dog_data["yaw"],
                    "velocity_x": dog_data["velocity_x"],
                    "velocity_y": dog_data["velocity_y"],
                    "yaw_speed": dog_data["yaw_speed"],
                    "voltage": dog_data["voltage"],
                    "current": dog_data["current"],
                    "mode_label": dog_data["mode_label"],
                    "motor_names": MOTOR_NAMES,
                }
                payload["sdk_ready"] = sdk_ready
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/camera_feed")
def camera_feed():
    def generate():
        while True:
            try:
                r = requests.get(f"{WEBRTC_BRIDGE_URL}/camera.jpg", timeout=2)
                if r.status_code == 200:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + r.content + b"\r\n"
                    )
            except requests.RequestException as e:
                logger.debug("camera proxy fetch failed: %s", e)
            time.sleep(0.1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/lidar_proxy")
def lidar_proxy():
    try:
        r = requests.get(f"{WEBRTC_BRIDGE_URL}/lidar", timeout=2)
        return Response(r.content, status=r.status_code, mimetype="application/json")
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.route("/data")
def data():
    def generate():
        while True:
            bridge_health = {"connected": False}
            try:
                r = requests.get(f"{WEBRTC_BRIDGE_URL}/health", timeout=2)
                if r.status_code == 200:
                    bridge_health = r.json()
            except requests.RequestException:
                pass

            with _lock:
                payload = dict(dog_data)
                payload["armed"] = _armed

            payload["sdk_ready"] = sdk_ready
            payload["bridge_connected"] = bridge_health.get("connected", False)

            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/arm", methods=["POST"])
def arm():
    if not sdk_ready:
        return jsonify({"error": "robot DDS connection not ready"}), 409
    _set_armed(True)
    return jsonify({"status": "armed"})


@app.route("/disarm", methods=["POST"])
def disarm():
    _set_armed(False)
    return jsonify({"status": "disarmed"})


@app.route("/update_joystick", methods=["POST"])
def update_joystick():
    if not _is_armed():
        return jsonify({"error": "not armed"}), 403
    if not sport_client:
        return jsonify({"error": "sdk not ready"}), 409

    payload = request.get_json(force=True)
    stick_id = payload.get("stickId")
    sx = float(payload.get("x", 0))
    sy = float(payload.get("y", 0))

    with _lock:
        if stick_id == "stick1":
            _move_state["x"] = -sy * MOVE_SPEED
            _move_state["y"] = -sx * MOVE_SPEED
        elif stick_id == "stick2":
            _move_state["yaw"] = -sx * TURN_SPEED
        x, y, yaw = _move_state["x"], _move_state["y"], _move_state["yaw"]

    try:
        sport_client.Move(x, y, yaw)
    except Exception:
        logger.exception("Move() failed")
        return jsonify({"error": "move command failed"}), 500

    _touch_activity()
    return jsonify({"status": "ok", "x": x, "y": y, "yaw": yaw})


@app.route("/run_action/<action_name>", methods=["POST"])
def run_action(action_name):
    if not _is_armed():
        return jsonify({"error": "not armed"}), 403
    action = _actions().get(action_name)
    if not action:
        return jsonify({"error": "unknown action"}), 404

    threading.Thread(target=action, daemon=True).start()
    _touch_activity()
    return jsonify({"status": f"running {action_name}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
