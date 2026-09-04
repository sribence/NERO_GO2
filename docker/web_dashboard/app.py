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
# same value for all four legs; per-leg sign flips happen in the pose
# functions below. Leg order everywhere here matches MOTOR_NAMES: FR,FL,RR,RL.
_STAND_HIP, _STAND_THIGH, _STAND_CALF = 0.0, 0.8, -1.5

# Diagonal-pair trot phase — FR+RL swing together, FL+RR in anti-phase.
# This (not literal mocap) is what makes the sinusoidal leg motion read as
# "walking" rather than just wobbling in place.
_TROT_PHASE = [0.0, math.pi, math.pi, 0.0]  # FR, FL, RR, RL


def _pose_stand(t):
    return [_STAND_HIP, _STAND_THIGH, _STAND_CALF] * 4


def _pose_walk(t):
    q = []
    for phase in _TROT_PHASE:
        swing = math.sin(t * 4.0 + phase)
        hip = _STAND_HIP + 0.05 * math.sin(t * 4.0 + phase + math.pi / 2)
        thigh = _STAND_THIGH + 0.35 * swing
        calf = _STAND_CALF - 0.25 * max(swing, 0.0)
        q.extend([hip, thigh, calf])
    return q


def _pose_wave(t):
    """FR leg lifts and waves side to side, the other three hold a stand —
    a stylised stand-in for the real SportClient.Hello() gesture (which we
    have no joint-trajectory data for; this is NOT a motion-captured
    reproduction of it, just a readable "waving" silhouette for the demo)."""
    q = [
        0.35 * math.sin(t * 5.0), 0.05, -0.55,  # FR: lifted + waving
        _STAND_HIP, _STAND_THIGH, _STAND_CALF,   # FL
        _STAND_HIP, _STAND_THIGH, _STAND_CALF,   # RR
        _STAND_HIP, _STAND_THIGH, _STAND_CALF,   # RL
    ]
    return q


def _pose_sit(t):
    """Rear legs tuck under, front legs stay extended — a seated posture."""
    wobble = 0.02 * math.sin(t * 1.5)
    q = []
    for leg_i in range(4):
        if leg_i in (2, 3):  # RR, RL — tucked
            q.extend([_STAND_HIP + wobble, 1.9, -2.6])
        else:  # FR, FL — stay standing
            q.extend([_STAND_HIP, _STAND_THIGH, _STAND_CALF + wobble])
    return q


def _pose_bow(t):
    """Front end dips in a slow bow/nod — our simplified stand-in for
    SportClient.Heart() (no real joint trajectory available for that either;
    labelled clearly in the UI as a stylised gesture, not the literal move)."""
    dip = 0.25 + 0.08 * math.sin(t * 2.0)
    q = []
    for leg_i in range(4):
        if leg_i in (0, 1):  # FR, FL — bow forward
            q.extend([_STAND_HIP, _STAND_THIGH + dip, _STAND_CALF - dip * 0.6])
        else:
            q.extend([_STAND_HIP, _STAND_THIGH, _STAND_CALF])
    return q


# Demo choreography: (label, duration_s, pose_fn, velocity_x_while_active).
# Cycles forever so a 45-90+ min showcase session never looks frozen or
# repeats too predictably. "Séta" gets the longest slot since walking gait
# is the most visually informative of the leg mechanics.
_SHOWCASE_SEQUENCE = [
    ("Állás", 3.0, _pose_stand, 0.0),
    ("Séta", 6.0, _pose_walk, 0.6),
    ("Állás", 2.0, _pose_stand, 0.0),
    ("Integetés", 3.5, _pose_wave, 0.0),
    ("Állás", 2.0, _pose_stand, 0.0),
    ("Ülés", 3.5, _pose_sit, 0.0),
    ("Állás", 2.0, _pose_stand, 0.0),
    ("Köszöntés (\"szív\")", 3.0, _pose_bow, 0.0),
]
_SHOWCASE_CYCLE_S = sum(seg[1] for seg in _SHOWCASE_SEQUENCE)


def _showcase_frame(t):
    """Picks the current choreography segment for time t and returns
    (label, joint_angles, velocity_x)."""
    phase_t = t % _SHOWCASE_CYCLE_S
    acc = 0.0
    for label, dur, pose_fn, vx in _SHOWCASE_SEQUENCE:
        if phase_t < acc + dur:
            return label, pose_fn(t), vx
        acc += dur
    return _SHOWCASE_SEQUENCE[0][0], _pose_stand(t), 0.0


def _init_mock_sdk():
    """MOCK_SDK=1 path — no unitree_sdk2py, no DDS, no real robot. Fills
    dog_data with plausible oscillating values (including the full 12-joint
    showcase choreography) on a timer, so the dashboard has something to
    show while developing the UI away from the robot (ld.
    docs/00-BIZTONSAGI-SZABALYOK.md — the robot is expensive/fragile/shared,
    so UI work should not require robot access)."""
    global sdk_ready, sport_client
    sport_client = _FakeSportClient()
    sdk_ready = True
    logger.info("MOCK SportClient ready (MOCK_SDK=1, no real robot involved)")
    t0 = time.time()
    while True:
        t = time.time() - t0
        label, q, vx = _showcase_frame(t)
        walking = label == "Séta"
        with _lock:
            dog_data["voltage"] = round(28.5 - 0.05 * math.sin(t * 0.2), 2)
            dog_data["current"] = round(1.0 + 0.3 * math.sin(t), 2)
            dog_data["avg_temp"] = round(35 + 2 * math.sin(t * 0.1), 1)
            dog_data["velocity_x"] = round(vx * math.sin(t * 0.5) if walking else vx, 2)
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
            dog_data["mode_label"] = label
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
