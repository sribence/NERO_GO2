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

import numpy as np
import requests
from flask import Flask, Response, jsonify, render_template, request

import lidar_mapping
import mission
import mock_streams
import mock_thermal
import speech

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nero_go2.web_dashboard")

app = Flask(__name__)

WEBRTC_BRIDGE_URL = os.environ.get("WEBRTC_BRIDGE_URL", "http://localhost:5001")
HESAI_BRIDGE_URL = os.environ.get("HESAI_BRIDGE_URL", "http://localhost:5003")
HESAI_DEVICE_IP = os.environ.get("HESAI_DEVICE_IP", "192.168.123.20")

# Kritikus tudományos-hitelességi jelölés a /showcase-hez: minden onnan
# kimenő adatcsomag jelzi, hogy szintetikus (mock) vagy valós robot-adat —
# ld. docs/14-capability-showcase-projekt.md, a workflow-brainstorm
# "tudományos lektor" szerepének első számú kritikus észrevétele.
DATA_SOURCE = "mock" if os.environ.get("MOCK_SDK") == "1" else "live"

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
    "position_x": None,
    "position_y": None,
    "position_z": None,
    "sport_yaw": None,
    "motor_q": [0.0] * 12,
    "motor_tau": [0.0] * 12,
    "motor_temp": [0] * 12,
    "roll": None,
    "pitch": None,
    "yaw": None,
    "mode_label": "—",
    "sport_state_time": None,
    "low_state_time": None,
}
_armed = False
_last_activity = time.time()
_move_state = {"x": 0.0, "y": 0.0, "yaw": 0.0}

sdk_ready = False
sport_client = None

# --- SLAM/térkép bridge (rosbridge websocketen, roslibpy-vel) ---------------
# A robot natív graph_pid_ws/QT_Server stackje (ld. docs/05-egyedi-slam-stack.md)
# occupancy grid térképet (nav_msgs/OccupancyGrid, "/map") és a robot pózát
# (/tf) publikálja ROS2-n. Ezt a docker/rosbridge (rosbridge_suite, :9090)
# teszi ki JSON-WebSocketen — mi csak OLVASUNK innen, sosem publikálunk,
# tehát ez a réteg soha nem tud mozgásparancsot küldeni a robotnak.
# A pontos topic/frame-nevek a 2026-09-04-i élő vizsgálat előtt csak
# feltételezettek — env-változóval felülírhatók, ha másnak bizonyulnak.
ROSBRIDGE_HOST = os.environ.get("ROSBRIDGE_HOST")  # ha üres, a SLAM-bridge nem indul el
ROSBRIDGE_PORT = int(os.environ.get("ROSBRIDGE_PORT", "9090"))
SLAM_BASE_FRAME = os.environ.get("SLAM_BASE_FRAME", "base_link")

_slam_lock = threading.Lock()
_slam_state = {
    "connected": False,
    "map": None,  # {width, height, resolution, origin_x, origin_y, data: [...]}
    "map_version": 0,
    "pose": None,  # {x, y, yaw}
}


def _quat_to_yaw(x, y, z, w):
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _slam_bridge_thread():
    import roslibpy

    while True:
        try:
            client = roslibpy.Ros(host=ROSBRIDGE_HOST, port=ROSBRIDGE_PORT)
            client.run(timeout=5)
            with _slam_lock:
                _slam_state["connected"] = client.is_connected
            logger.info("SLAM bridge: connected to rosbridge at %s:%s", ROSBRIDGE_HOST, ROSBRIDGE_PORT)

            def on_map(msg):
                info = msg["info"]
                with _slam_lock:
                    _slam_state["map"] = {
                        "width": info["width"],
                        "height": info["height"],
                        "resolution": info["resolution"],
                        "origin_x": info["origin"]["position"]["x"],
                        "origin_y": info["origin"]["position"]["y"],
                        "data": msg["data"],
                    }
                    _slam_state["map_version"] += 1

            def on_tf(msg):
                for t in msg.get("transforms", []):
                    if t.get("child_frame_id") != SLAM_BASE_FRAME:
                        continue
                    trans = t["transform"]["translation"]
                    rot = t["transform"]["rotation"]
                    with _slam_lock:
                        _slam_state["pose"] = {
                            "x": trans["x"],
                            "y": trans["y"],
                            "yaw": _quat_to_yaw(rot["x"], rot["y"], rot["z"], rot["w"]),
                        }

            map_topic = roslibpy.Topic(client, "/map", "nav_msgs/OccupancyGrid")
            map_topic.subscribe(on_map)
            tf_topic = roslibpy.Topic(client, "/tf", "tf2_msgs/TFMessage")
            tf_topic.subscribe(on_tf)

            while client.is_connected:
                time.sleep(1)
        except Exception:
            logger.exception("SLAM bridge: rosbridge connection failed, retrying in 5s")
        with _slam_lock:
            _slam_state["connected"] = False
        time.sleep(5)


if ROSBRIDGE_HOST:
    threading.Thread(target=_slam_bridge_thread, daemon=True).start()
else:
    logger.info("ROSBRIDGE_HOST not set — SLAM/map bridge disabled")


# --- Intel RealSense D435i bridge (külön ROS1 Noetic rosbridge, ld.
# ../realsense_bridge/) — ugyanaz a minta, mint a fenti SLAM-bridge, csak
# másik rosbridge-porton (a ROS1/ROS2 rosbridge egymástól függetlenül,
# akár egyszerre is futhat). Csak OLVASUNK innen is — szín-kép + mélység-
# pontfelhő, sosem publikálunk vissza, tehát ez sem tud a robotnak
# parancsot küldeni.
REALSENSE_ROSBRIDGE_HOST = os.environ.get("REALSENSE_ROSBRIDGE_HOST", "127.0.0.1")
REALSENSE_ROSBRIDGE_PORT = int(os.environ.get("REALSENSE_ROSBRIDGE_PORT", "9091"))

_realsense_lock = threading.Lock()
_realsense_state = {
    "connected": False,
    "color_jpg_b64": None,  # a legutóbbi szín-képkocka, JPEG, base64-ben (közvetlenül <img src="data:...">-be tehető)
    "depth_jpg_b64": None,  # a színezett 2D mélységtérkép JPEG base64-ben
    "points": None,  # letisztított/ritkított [x,y,z] lista a mélység-pontfelhőből
}



def _decode_pointcloud2(msg):
    """sensor_msgs/PointCloud2 base64-dekódolása [x,y,z] listává — a
    rosbridge JSON-üzenetben a bináris 'data' mező base64 stringként jön.
    Ritkítunk (max ~4000 pont), hogy a JSON-válasz és a three.js renderelés
    ne nőjön parttalanul nagyra egy sűrű RealSense-felhőn."""
    import base64
    import struct

    raw = base64.b64decode(msg["data"])
    point_step = msg["point_step"]
    offsets = {f["name"]: f["offset"] for f in msg["fields"]}
    if "x" not in offsets or "y" not in offsets or "z" not in offsets:
        return []
    n_points = len(raw) // point_step
    step = max(1, n_points // 4000)
    points = []
    for i in range(0, n_points, step):
        base = i * point_step
        x = struct.unpack_from("<f", raw, base + offsets["x"])[0]
        y = struct.unpack_from("<f", raw, base + offsets["y"])[0]
        z = struct.unpack_from("<f", raw, base + offsets["z"])[0]
        if x != x or y != y or z != z:  # NaN-szűrés (érvénytelen mélységpont)
            continue
        points.append([round(x, 3), round(y, 3), round(z, 3)])
    return points


def _realsense_bridge_thread():
    import roslibpy

    while True:
        try:
            client = roslibpy.Ros(host=REALSENSE_ROSBRIDGE_HOST, port=REALSENSE_ROSBRIDGE_PORT)
            client.run(timeout=5)
            with _realsense_lock:
                _realsense_state["connected"] = client.is_connected
            logger.info("RealSense bridge: connected to rosbridge at %s:%s", REALSENSE_ROSBRIDGE_HOST, REALSENSE_ROSBRIDGE_PORT)

            def on_color(msg):
                with _realsense_lock:
                    _realsense_state["color_jpg_b64"] = msg["data"]  # már base64 string a rosbridge JSON-ban

            def on_points(msg):
                pts = _decode_pointcloud2(msg)
                with _realsense_lock:
                    _realsense_state["points"] = pts

            def on_depth_colorized(msg):
                with _realsense_lock:
                    _realsense_state["depth_jpg_b64"] = msg["data"]

            color_topic = roslibpy.Topic(client, "/camera/color/image_raw/compressed", "sensor_msgs/CompressedImage")
            color_topic.subscribe(on_color)
            depth_color_topic = roslibpy.Topic(client, "/camera/depth/colorized/compressed", "sensor_msgs/CompressedImage")
            depth_color_topic.subscribe(on_depth_colorized)
            points_topic = roslibpy.Topic(client, "/camera/depth/color/points", "sensor_msgs/PointCloud2")
            points_topic.subscribe(on_points)

            while client.is_connected:
                time.sleep(1)
        except Exception:
            logger.exception("RealSense bridge: rosbridge connection failed, retrying in 5s")
        with _realsense_lock:
            _realsense_state["connected"] = False
        time.sleep(5)


if REALSENSE_ROSBRIDGE_HOST:
    threading.Thread(target=_realsense_bridge_thread, daemon=True).start()
else:
    logger.info("REALSENSE_ROSBRIDGE_HOST not set — RealSense bridge disabled")


def _touch_activity():
    global _last_activity
    with _lock:
        _last_activity = time.time()


def _is_armed():
    with _lock:
        return _armed


def _set_armed(value: bool):
    # FONTOS: _armed és _last_activity EGY lock alatt frissül — külön
    # lock-acquire esetén a _watchdog pont a kettő között kaphatja el (armed
    # már True, last_activity még régi), és rögtön visszazárolja (ld.
    # 2026-09-05 esti élő hiba, ahol az élesítés sosem maradt meg).
    global _armed, _last_activity
    with _lock:
        _armed = value
        if value:
            _last_activity = time.time()
    if not value:
        try:
            with _macro_lock:
                _macro_state["abort_flag"] = True
        except NameError:
            pass


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


# --- Navigáció: moduláris P-szabályozó + célpont-állapotgép ---------------
# Biztonsági megjegyzés (2026-09-04): ez a robotot TÉNYLEGESEN mozgatja,
# felügyelet nélkül, amíg armed és van célpont — ezért jóval óvatosabb
# sebesség-korlátokkal megy, mint a kézi joystick, és MINDIG az _is_armed()
# kapun át fut. A bemutatón ez csak elkerített, felügyelt "bónusz demó",
# a fő vezérlés a joystick marad.
NAV_MAX_VX = 0.25  # m/s — a joystick MOVE_SPEED-jénél (0.5) jóval óvatosabb
NAV_MAX_VYAW = 0.5  # rad/s
NAV_KP_LIN = 0.6
NAV_KP_ANG = 1.2
NAV_GOAL_TOLERANCE_M = 0.2
NAV_HEADING_GATE_RAD = 0.35  # ennél nagyobb szögeltérésnél NEM megy előre, csak fordul

_nav_lock = threading.Lock()
_nav_state = {
    "target": None,  # {"x":, "y":, "action": (opcionális)}
    "queue": [],  # további célpontok script-módban
    "last_status": None,  # a frontendnek szóló utolsó esemény
}


def _normalize_angle(angle):
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def compute_nav_command(pose, target):
    """TISZTA, SDK-független P-szabályozó függvény — csak a jelenlegi pózt
    (dict: x, y, yaw) és a célpontot (dict: x, y) kapja paraméterként,
    visszaad egy (vx, vy, vyaw, reached) tuple-t. Semmilyen globális
    állapotot nem olvas/ír, nem hív SDK-t — ezért egyszerűen tesztelhető,
    és holnap reggel változtatás nélkül bekötendő az éles SportClient.Move()
    hívás elé (ld. _navigation_thread, ami ezt körbecsomagolja)."""
    dx = target["x"] - pose["x"]
    dy = target["y"] - pose["y"]
    dist = math.hypot(dx, dy)
    if dist < NAV_GOAL_TOLERANCE_M:
        return 0.0, 0.0, 0.0, True

    target_yaw = math.atan2(dy, dx)
    heading_error = _normalize_angle(target_yaw - pose["yaw"])
    vyaw = max(-NAV_MAX_VYAW, min(NAV_MAX_VYAW, NAV_KP_ANG * heading_error))
    if abs(heading_error) > NAV_HEADING_GATE_RAD:
        vx = 0.0  # előbb helyben forog a cél felé, csak utána indul el
    else:
        vx = max(0.0, min(NAV_MAX_VX, NAV_KP_LIN * dist))
    return vx, 0.0, vyaw, False


# Autonóm térképi navigáció: zárt hurkú P-szabályozó a robot sport-odometriája alapján.
# Csak élesített (ARM) állapotban ad ki mozgásparancsot (SportClient.Move()).
NAV_MOVE_ROBOT = True
NAV_SIMULATED_TRAVEL_S = 2.5  # tartalék szimulált idő disarmed állapotban


def _navigation_thread():
    simulated_deadline = None
    while True:
        time.sleep(0.1)
        with _nav_lock:
            target = _nav_state["target"]
        if not target:
            simulated_deadline = None
            continue

        if not NAV_MOVE_ROBOT:
            # Szimulált mód: nincs Move()-hívás, csak egy időzített "megérkezés"
            # a UI/fotó-demó kedvéért — a robot fizikailag egy helyben marad.
            if simulated_deadline is None:
                simulated_deadline = time.time() + NAV_SIMULATED_TRAVEL_S
            if time.time() < simulated_deadline:
                continue
            simulated_deadline = None
            reached = True
        else:
            if not _is_armed() or not sport_client:
                continue
            with _lock:
                # sport_yaw, NEM "yaw" — a position-nel szinkron kell a
                # navigációhoz (ld. pose_snapshot kommentje).
                rx, ry, ryaw = dog_data["position_x"], dog_data["position_y"], dog_data["sport_yaw"]
            if rx is None or ry is None or ryaw is None:
                continue
            vx, vy, vyaw, reached = compute_nav_command({"x": rx, "y": ry, "yaw": ryaw}, target)
            try:
                sport_client.Move(vx, vy, vyaw)
            except Exception:
                logger.exception("Nav: Move() failed")
            _touch_activity()
            if reached:
                try:
                    sport_client.Move(0, 0, 0)
                except Exception:
                    pass

        if reached:
            photo_url = _capture_photo() if target.get("action") == "photo" else None
            with _nav_lock:
                _nav_state["last_status"] = {
                    "type": "reached",
                    "x": target["x"],
                    "y": target["y"],
                    "action": target.get("action"),
                    "photo_url": photo_url,
                }
                if _nav_state["queue"]:
                    _nav_state["target"] = _nav_state["queue"].pop(0)
                else:
                    _nav_state["target"] = None


def _capture_photo(waypoint_id=None):
    """Fényképező akciópont — kimenti az aktuális kamera-képkockát. MOCK
    módban (nincs webrtc_bridge lokálisan) egy előre elkészített kép-
    placeholder-t használ, hogy a frontend-lánc (SSE esemény -> oldalsáv
    -> térkép-bélyegkép) végigtesztelhető legyen ma este. Holnap reggel
    a webrtc_bridge már fut, a valós /camera.jpg-t menti.

    waypoint_id: opcionális — a mission-runner "photo" task-ja adja át, hogy
    a fájlnév a waypoint-azonosítót is tartalmazza (timestamp+waypoint-id),
    ld. docs/20-egyrobot-mission-taszklista.md."""
    suffix = f"_wp{waypoint_id}" if waypoint_id is not None else ""
    filename = f"photo_{int(time.time())}{suffix}.jpg"
    dest = os.path.join(os.path.dirname(__file__), "static", "photos", filename)
    # 2026-09-17: a static/photos/ mappa nem létezett a repóban (csak
    # static/maps/ volt becsomagolva) — ez a mission "photo" task-ja nélkül
    # eddig rejtve maradt, mert nem volt semmi, ami rendszeresen hívja
    # _capture_photo()-t. Az os.makedirs itt biztonságos/idempotens.
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        resp = requests.get(f"{WEBRTC_BRIDGE_URL}/camera.jpg", timeout=2)
        if resp.status_code == 200:
            with open(dest, "wb") as f:
                f.write(resp.content)
            return f"/static/photos/{filename}"
    except requests.RequestException:
        pass
    placeholder = os.path.join(os.path.dirname(__file__), "static", "maps", "demo_map.png")
    try:
        with open(placeholder, "rb") as src, open(dest, "wb") as f:
            f.write(src.read())
        return f"/static/photos/{filename}"
    except OSError:
        logger.exception("_capture_photo: placeholder copy failed")
        return None


threading.Thread(target=_navigation_thread, daemon=True).start()


# --- Mission/task-queue wiring (ld. mission.py) ---------------------------
# Egyrobot (Go2-only) küldetés-futtató — a TODO.md szerinti multi-robot
# (Xavier+Go2) core-refaktor NINCS bekötve, csak ez az egyetlen Go2-t
# vezérlő réteg. A MissionRunner-nek átadott 3 kis helper-függvény a MEGLÉVŐ
# _nav_state-et írja/olvassa, ugyanazt, amit az /api/navigate,
# /api/navigate/cancel és /nav_status route is használ — a mission-runner
# tehát nem egy párhuzamos, önálló mozgás-útvonal, hanem ugyanazon az
# armed-kapun megy át, mint a kézi/egypontos navigáció.
def _navigate_single(x, y):
    """Egypontos navigáció indítása a mission-runner számára — ugyanaz az
    _nav_state, mint az /api/navigate route-nál, csak Flask-request nélkül."""
    if not _is_armed():
        raise RuntimeError("not armed")
    with _nav_lock:
        _nav_state["target"] = {"x": float(x), "y": float(y), "action": None}
        _nav_state["queue"] = []
        _nav_state["last_status"] = {"type": "started", "target": dict(_nav_state["target"])}
    _touch_activity()


def _cancel_navigation():
    """Ugyanaz a leállítás, mint az /api/navigate/cancel route — kiszervezve,
    hogy a mission-runner abort() is meghívhassa Flask-request nélkül."""
    with _nav_lock:
        _nav_state["target"] = None
        _nav_state["queue"] = []
        _nav_state["last_status"] = {"type": "cancelled"}
    _safe_stop_move("mission abort")


def _nav_reached(x, y, tol=0.05):
    """True, ha a legutóbbi navigáció-ciklus PONTOSAN ezt a célpontot érte el
    ("reached" last_status + nincs aktív target) — NEM elég, hogy a target
    None legyen, mert cancel/estop is None-ra állítja last_status típus
    nélkül/mással, és azt itt nem szabad "megérkezés"-ként félreérteni."""
    with _nav_lock:
        target = _nav_state["target"]
        last_status = _nav_state["last_status"]
    if target is not None:
        return False
    if not last_status or last_status.get("type") != "reached":
        return False
    return abs(last_status.get("x", 1e9) - x) < tol and abs(last_status.get("y", 1e9) - y) < tol


def _mission_run_pose_action(action_name):
    """"pose" task — egy meglévő /run_action-nek megfelelő mozdulat (pl.
    wave/sit), de szinkron hívva (nem külön szálban), mert a mission-runner
    saját maga már egy háttérszálban fut, és tudnia kell, mikor fejeződött
    be, mielőtt a következő waypointra megy."""
    if not _is_armed():
        raise RuntimeError("not armed")
    action = _actions().get(action_name or "sit")
    if not action:
        raise RuntimeError(f"unknown pose action: {action_name}")
    action()
    _touch_activity()


def _mission_lie_down():
    """"lie_down" task — a meglévő StandDown ("lay_down") akció, szinkron
    hívva, ugyanazzal az armed-kapuval, mint bármelyik mozgás-parancs."""
    if not _is_armed():
        raise RuntimeError("not armed")
    action = _actions().get("lay_down")
    if not action:
        raise RuntimeError("sdk not ready")
    action()
    _touch_activity()


# _mission.py default charge_dock_fn-je (log "would dock here", ok=False)
# pont megfelel a task-leírásnak — nincs valós dokkoló-station integráció
# ebben a repóban (ld. grep eredmény: "dock"/"charg" sehol az app.py-ban
# hardware-kontextusban), ezért itt nem adunk felül semmit, a mission
# modul saját stub-ját használjuk.
_mission_runner = mission.MissionRunner(
    is_armed_fn=_is_armed,
    navigate_to_fn=_navigate_single,
    cancel_navigate_fn=_cancel_navigation,
    nav_reached_fn=_nav_reached,
    run_pose_action_fn=_mission_run_pose_action,
    capture_photo_fn=_capture_photo,
    lie_down_fn=_mission_lie_down,
)


# --- Mozgás Makró & Útvonal Rögzítő / Visszajátszó Motor (Macro Subsystem) ---
MACRO_DIR = os.path.join(os.path.dirname(__file__), "macros")
os.makedirs(MACRO_DIR, exist_ok=True)

_macro_lock = threading.Lock()
_macro_state = {
    "recording": False,
    "record_start_t": 0.0,
    "record_name": "",
    "samples": [],
    "waypoints": [],
    "pending_action": None,
    "playing": False,
    "play_thread": None,
    "play_macro_name": "",
    "play_progress": {
        "current_t": 0.0,
        "total_t": 0.0,
        "pct": 0,
        "status": "idle"
    },
    "abort_flag": False,
}


def _macro_record_worker():
    """10 Hz-es mintavevő szál a kézi mozgások és pozíciók rögzítéséhez."""
    while True:
        time.sleep(0.1)
        with _macro_lock:
            if not _macro_state["recording"]:
                continue
            t_start = _macro_state["record_start_t"]
            pending_act = _macro_state["pending_action"]
            _macro_state["pending_action"] = None

        t_rel = round(time.time() - t_start, 3)
        with _lock:
            vx = _move_state["x"]
            vy = _move_state["y"]
            vyaw = _move_state["yaw"]
            rx = dog_data.get("position_x")
            ry = dog_data.get("position_y")
            ryaw = dog_data.get("sport_yaw")

        sample = {
            "t": t_rel,
            "vx": round(vx, 3),
            "vy": round(vy, 3),
            "vyaw": round(vyaw, 3),
            "x": round(rx, 3) if rx is not None else 0.0,
            "y": round(ry, 3) if ry is not None else 0.0,
            "yaw": round(ryaw, 3) if ryaw is not None else 0.0,
            "action": pending_act,
        }
        with _macro_lock:
            if _macro_state["recording"]:
                _macro_state["samples"].append(sample)


threading.Thread(target=_macro_record_worker, daemon=True).start()


def _macro_playback_worker(macro_data, speed):
    """Zárt hurkú, térbeli koordinátákra navigáló makró visszajátszó motor.
    A rögzített (X, Y) koordinátákhoz vezeti a robotot a valós térben P-szabályozóval,
    ahelyett, hogy vakon, nyílt hurokban ismételné a sebességparancsokat."""
    name = macro_data.get("name", "unnamed")
    waypoints = macro_data.get("waypoints", [])
    samples = macro_data.get("samples", [])

    # Célpontok kiválasztása:
    # 1. Ha vannak explicit mentett útpontok (user lerakott pontok), azokat járjuk be sorban.
    # 2. Ha nincsenek, a folytonos mintákból kinyerjük a térbeli nyomvonalat ~0.35m-es lépésekben.
    if waypoints and len(waypoints) > 0:
        targets = [dict(w) for w in waypoints]
    elif samples and len(samples) > 0:
        targets = []
        for i, s in enumerate(samples):
            if i == 0 or i == len(samples) - 1 or s.get("action"):
                targets.append(dict(s))
            else:
                last = targets[-1]
                dist = math.hypot(s.get("x", 0.0) - last.get("x", 0.0), s.get("y", 0.0) - last.get("y", 0.0))
                if dist >= 0.35:
                    targets.append(dict(s))
    else:
        with _macro_lock:
            _macro_state["playing"] = False
            _macro_state["play_progress"]["status"] = "done"
        return

    s = max(0.2, min(1.0, float(speed)))
    total_targets = len(targets)
    logger.info("Makró térbeli visszajátszás indítása: '%s' %.2fx sebességgel (%d célpont)", name, s, total_targets)

    with _macro_lock:
        _macro_state["play_macro_name"] = name
        _macro_state["play_progress"] = {
            "current_t": 0.0,
            "total_t": round(macro_data.get("duration_s", total_targets * 3.0) / s, 1),
            "pct": 0,
            "status": "playing"
        }

    MAX_SAFE_VX = 0.25
    MAX_SAFE_VYAW = 0.45
    WP_TIMEOUT_S = 35.0  # max 35mp célpontonként az elakadás kivédésére

    play_start_wall = time.time()

    try:
        for wp_idx, target in enumerate(targets):
            with _macro_lock:
                if _macro_state["abort_flag"]:
                    logger.info("Makró visszajátszás megszakítva (abort flag)")
                    break
            if not _is_armed():
                logger.warning("Makró visszajátszás megszakítva: robot zárolva (disarmed)")
                break

            tx = float(target.get("x", 0.0))
            ty = float(target.get("y", 0.0))
            target_pose = {"x": tx, "y": ty}
            wp_start = time.time()

            logger.info("Makró navigálás célponthoz #%d/%d: (x=%.2f, y=%.2f)", wp_idx + 1, total_targets, tx, ty)

            # Zárt hurkú P-szabályozás az adott térbeli pont eléréséig
            while time.time() - wp_start < WP_TIMEOUT_S:
                with _macro_lock:
                    aborted = _macro_state["abort_flag"]
                if aborted or not _is_armed():
                    break

                with _lock:
                    rx = dog_data.get("position_x")
                    ry = dog_data.get("position_y")
                    ryaw = dog_data.get("sport_yaw")

                if rx is None or ry is None or ryaw is None:
                    time.sleep(0.05)
                    continue

                vx, vy, vyaw, reached = compute_nav_command({"x": rx, "y": ry, "yaw": ryaw}, target_pose)
                if reached:
                    if sport_client:
                        try:
                            sport_client.Move(0, 0, 0)
                        except Exception:
                            pass
                    break

                # Sebességskálázás a csúszka értéke alapján
                vx_cmd = max(-MAX_SAFE_VX, min(MAX_SAFE_VX, vx * s))
                vyaw_cmd = max(-MAX_SAFE_VYAW, min(MAX_SAFE_VYAW, vyaw * s))

                if sport_client:
                    try:
                        sport_client.Move(vx_cmd, 0.0, vyaw_cmd)
                    except Exception:
                        logger.exception("Makró Move() sikertelen")

                _touch_activity()

                elapsed = time.time() - play_start_wall
                pct = min(99, int(((wp_idx + 0.5) / total_targets) * 100))
                with _macro_lock:
                    _macro_state["play_progress"]["current_t"] = round(elapsed, 1)
                    _macro_state["play_progress"]["pct"] = pct

                time.sleep(0.05)

            with _macro_lock:
                if _macro_state["abort_flag"] or not _is_armed():
                    break

            # Célponton rögzített akció lefuttatása (pl. sit, hello, wave)
            action_name = target.get("action")
            if action_name and not str(action_name).startswith("waypoint:"):
                if sport_client:
                    try:
                        sport_client.Move(0, 0, 0)
                    except Exception:
                        pass
                action_func = _actions().get(action_name)
                if action_func:
                    logger.info("Makró útpont akció végrehajtása: %s", action_name)
                    try:
                        action_func()
                    except Exception:
                        logger.exception("Makró akció sikertelen: %s", action_name)
                    action_deadline = time.time() + 3.5
                    while time.time() < action_deadline:
                        with _macro_lock:
                            aborted = _macro_state["abort_flag"]
                        if aborted or not _is_armed():
                            break
                        _touch_activity()
                        time.sleep(0.05)

            elapsed = time.time() - play_start_wall
            pct = min(100, int(((wp_idx + 1) / total_targets) * 100))
            with _macro_lock:
                _macro_state["play_progress"]["current_t"] = round(elapsed, 1)
                _macro_state["play_progress"]["pct"] = pct

    finally:
        if sport_client:
            try:
                sport_client.Move(0, 0, 0)
            except Exception:
                pass
        with _macro_lock:
            _macro_state["playing"] = False
            final_status = "aborted" if _macro_state["abort_flag"] or not _is_armed() else "done"
            _macro_state["play_progress"]["status"] = final_status
            if final_status == "done":
                _macro_state["play_progress"]["pct"] = 100
        logger.info("Makró térbeli visszajátszás befejeződött, állapot: %s", final_status)


# --- Security mód: objektumkövetés (mock ma este, ld. docs/15) -----------

TRACK_MAX_VYAW = 0.4
TRACK_KP_ANG = 1.0
TRACK_CENTER_TOLERANCE = 0.06  # a bbox-közép ennyin belül van a képközéptől -> nem forog tovább


def compute_tracking_command(bbox_center_x, frame_width=1.0):
    """TISZTA, SDK-független függvény — a bbox vízszintes középpontját kapja
    (0..frame_width skálán) és visszaadja a vyaw-t, hogy a cél a képközépre
    kerüljön. Nincs detekció esetén hívd bbox_center_x=None-nal -> (0.0, False)."""
    if bbox_center_x is None:
        return 0.0, False
    offset = (bbox_center_x / frame_width) - 0.5  # -0.5..+0.5, 0 = középen
    if abs(offset) < TRACK_CENTER_TOLERANCE:
        return 0.0, True
    vyaw = max(-TRACK_MAX_VYAW, min(TRACK_MAX_VYAW, -TRACK_KP_ANG * offset))
    return vyaw, True


_security_lock = threading.Lock()
_security_state = {"active": False, "detected": False, "bbox": None, "confidence": 0.0, "last_event": None}


def _mock_trigger_light():
    logger.info("[MOCK ACTION] robot lámpa BE (holnap: valós SDK-hívás)")


def _mock_play_audio():
    logger.info("[MOCK ACTION] hangfájl lejátszás: halt.mp3 (holnap: valós audio-hívás)")


def _security_thread():
    t0 = time.time()
    was_detected = False
    while True:
        time.sleep(0.2)
        with _security_lock:
            active = _security_state["active"]
        if not active:
            was_detected = False
            continue

        det = mock_streams.mock_detection(time.time() - t0)
        with _security_lock:
            _security_state["detected"] = det["detected"]
            _security_state["bbox"] = det["bbox"]
            _security_state["confidence"] = det["confidence"]

        if det["detected"] and not was_detected:
            _mock_trigger_light()
            _mock_play_audio()
            with _security_lock:
                _security_state["last_event"] = {"type": "intruder_detected", "t": time.time()}
        was_detected = det["detected"]

        if not _is_armed() or not sport_client:
            continue
        if det["detected"] and det["bbox"]:
            bbox_center_x = (det["bbox"][0] + det["bbox"][2]) / 2.0
            vyaw, tracking = compute_tracking_command(bbox_center_x, frame_width=1.0)
        else:
            vyaw, tracking = 0.0, False
        try:
            sport_client.Move(0.0, 0.0, vyaw if tracking else 0.0)
        except Exception:
            logger.exception("Security: Move() failed")
        _touch_activity()


threading.Thread(target=_security_thread, daemon=True).start()


# --- "Kövesd az embert" mód (YOLO) -----------------------------------------
# A steering-matek (compute_follow_command/pick_person_target/person_lost)
# tiszta, SDK-független függvényekben él person_follow.py-ban, ugyanúgy,
# mint a fenti compute_tracking_command/compute_nav_command minta — csak ez
# a szál köti be sport_client.Move()-ba, ami MÁR a meglévő armed-kapu +
# watchdog + E-stop alatt fut. Nincs itt semmilyen új, hardver-felé közvetlen
# parancsút (nincs LowCmd, nincs joint-szintű írás).
#
# A YOLO-detektor (ultralytics) a testvér docker/realsense_bridge szolgáltatás
# prototípusa (yolo_detector.py) — ez sosem futott élesben a roboton. Lusta
# importtal töltjük be (csak amikor /api/follow/start tényleg elindul), hogy
# a dashboard ultralytics/cv2 nélkül (pl. tiszta MOCK_SDK UI-fejlesztés) is
# elinduljon.
from person_follow import (  # noqa: E402
    FOLLOW_PERSON_LOST_TIMEOUT_S,
    compute_follow_command,
    person_lost,
    pick_person_target,
)

_REALSENSE_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "realsense_bridge")
FOLLOW_LOOP_INTERVAL_S = 0.2

_follow_lock = threading.Lock()
_follow_state = {
    "active": False,
    "detected": False,
    "bbox": None,
    "confidence": 0.0,
    "vx": 0.0,
    "vyaw": 0.0,
    "last_event": None,
}


def _load_yolo_detect():
    """A realsense_bridge testvér-szolgáltatás yolo_detector.detect()
    függvénye — sys.path-bővítéssel, mert két külön docker-szolgáltatás
    (más konténer, más requirements.txt), nem csomagolt Python-package."""
    import sys

    if _REALSENSE_BRIDGE_DIR not in sys.path:
        sys.path.insert(0, _REALSENSE_BRIDGE_DIR)
    from yolo_detector import detect  # ultralytics import ITT történik meg

    return detect


def _safe_stop_move(reason):
    """A robot lezárt megállítása — ha az SDK ismeri a StopMove()-ot,
    azt hívjuk (ez a dedikált "állítsd meg a jelenlegi Move()-sebességet"
    hívás), különben ugyanaz a Move(0,0,0) fallback, amit a kódbázis
    mindenhol máshol is használ (ld. api_navigate_cancel/api_estop/
    security_stop). Sosem dob kifelé kivételt."""
    if not sport_client:
        return
    stop_fn = getattr(sport_client, "StopMove", None)
    try:
        if callable(stop_fn):
            stop_fn()
        else:
            sport_client.Move(0, 0, 0)
    except Exception:
        logger.exception("%s: stop command failed", reason)


def _follow_thread():
    import cv2

    try:
        detect = _load_yolo_detect()
    except Exception:
        logger.exception("Follow: YOLO detector could not be loaded (ultralytics/cv2 hiányzik?) - leáll")
        with _follow_lock:
            _follow_state["active"] = False
            _follow_state["last_event"] = {"type": "error", "message": "yolo unavailable", "t": time.time()}
        return

    last_seen = None
    was_stopped = True  # ne spammeljük a StopMove-ot minden ticknél, ha már állunk
    logger.info("Follow: thread elindult")

    while True:
        with _follow_lock:
            if not _follow_state["active"]:
                return  # /api/follow/stop kérte - ez a szál itt véget ér

        frame = None
        try:
            resp = requests.get(f"{WEBRTC_BRIDGE_URL}/camera.jpg", timeout=1.0)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except requests.RequestException:
            frame = None
        except Exception:
            logger.exception("Follow: kamera-képkocka dekódolása sikertelen")
            frame = None

        now = time.time()
        target = None
        if frame is not None:
            try:
                result = detect(frame)
                target = pick_person_target(result.get("detections"))
            except Exception:
                logger.exception("Follow: YOLO detect() sikertelen")
                target = None

        if target is not None:
            last_seen = now
            h, w = frame.shape[:2]
            vx, vyaw = compute_follow_command(target["bbox"], w, h)
            with _follow_lock:
                _follow_state["detected"] = True
                _follow_state["bbox"] = target["bbox"]
                _follow_state["confidence"] = target["confidence"]
                _follow_state["vx"] = vx
                _follow_state["vyaw"] = vyaw
            was_stopped = False
            if _is_armed() and sport_client:
                try:
                    sport_client.Move(vx, 0.0, vyaw)
                except Exception:
                    logger.exception("Follow: Move() failed")
                _touch_activity()
        else:
            with _follow_lock:
                _follow_state["detected"] = False
                _follow_state["bbox"] = None
                _follow_state["confidence"] = 0.0
            if person_lost(last_seen, now, FOLLOW_PERSON_LOST_TIMEOUT_S) and not was_stopped:
                logger.info("Follow: nincs szemely-detekcio %.1fs ota, megallitas", FOLLOW_PERSON_LOST_TIMEOUT_S)
                _safe_stop_move("Follow (person lost)")
                _touch_activity()
                with _follow_lock:
                    _follow_state["vx"] = 0.0
                    _follow_state["vyaw"] = 0.0
                    _follow_state["last_event"] = {"type": "person_lost", "t": now}
                was_stopped = True

        time.sleep(FOLLOW_LOOP_INTERVAL_S)


# --- Élő occupancy grid ("Robotporszívó mód") -----------------------------
# 2026-09-05, bemutató napja: a tegnap esti docker/mapping/build_map.py
# offline logikájának ÉLŐ, inkrementális változata — valós hesai_bridge
# pontfelhő + valós SDK-odometria (position_x/y + sport_yaw), CSAK OLVAS,
# sosem küld mozgásparancsot. A 90 fokos szenzor-extrinsic korrekció és a
# Z-sáv/dőlés-szűrés ugyanaz, mint a tegnap esti kalibrációban (ld. docs/15).
LIVE_MAP_RESOLUTION = 0.05
LIVE_MAP_SIZE_M = 20.0
LIVE_MAP_Z_BAND = 0.05
LIVE_MAP_MIN_RANGE = 0.5
LIVE_MAP_MAX_RANGE = 5.0
LIVE_MAP_MAX_TILT_RAD = 0.30
LIVE_MAP_MAX_YAW_SPEED = 0.35  # rad/s — ennél gyorsabb forgásnál kihagyjuk a térkép-frissítést
LIVE_MAP_YAW_OFFSET = math.radians(90)

# --- Log-odds valószínűségi térkép (a naiv "hit-számlálás" helyett) -------
# 2026-09-05, user visszajelzése alapján: a korábbi egyszerű hit_counts-os
# módszer zajos volt — a falak folyamatosan újrarajzolódtak és vastagodtak,
# mert egyetlen kósza pont ugyanúgy számított, mint egy megbízható, sokszor
# látott fal. A valódi SLAM-rendszerek (és a robotporszívók) ehelyett
# log-odds Bayes-frissítést használnak: minden észlelés csak KICSIT tolja el
# a cella "biztos fal" / "biztos szabad" hitét, telítve egy határnál — így
# egy stabil megfigyelés idővel magabiztos, VÉKONY fallá áll össze, egy
# elszigetelt zajpont pedig nem tudja felülírni.
# 2026-09-17: a log-odds/Bresenham/cella-konverziós math kiszervezve a
# lidar_mapping.py-ba (dependency-light, app.py importja nélkül tesztelhető
# — ld. docker/web_dashboard/tests/test_lidar_mapping.py). Itt csak a
# konstansok referenciái maradnak, hogy a lenti kód ne törjön.
LOGODDS_HIT = lidar_mapping.LOGODDS_HIT
LOGODDS_MISS = lidar_mapping.LOGODDS_MISS
LOGODDS_MIN = lidar_mapping.LOGODDS_MIN
LOGODDS_MAX = lidar_mapping.LOGODDS_MAX
LOGODDS_OCC_THRESH = lidar_mapping.LOGODDS_OCC_THRESH
LOGODDS_FREE_THRESH = lidar_mapping.LOGODDS_FREE_THRESH

# 2026-09-17: periodikus PNG-mentés a felhalmozott térképről, hogy a mai
# esti tesztfutás(ok) és a holnap reggeli valódi roboton futó élő térkép is
# nyomot hagyjon a diszken, ne csak a memóriában éljen a folyamat futása
# alatt. Lásd docs/18-elo-terkep-perzisztencia-2026-09-17.md.
LIVE_MAP_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "static", "maps", "live_map.png")
LIVE_MAP_SNAPSHOT_INTERVAL_S = 10.0
_live_map_snapshot_scheduler = lidar_mapping.SnapshotScheduler(LIVE_MAP_SNAPSHOT_INTERVAL_S)

_live_map_lock = threading.Lock()
_live_map_state = {
    "ready": False,
    "grid": None,
    "log_odds": None,
    "resolution": LIVE_MAP_RESOLUTION,
    "origin_x": None,
    "origin_y": None,
    "cells": 0,
    "snapshot_url": None,
    "snapshot_saved_at": None,
}


def _live_map_update_once():
    with _lock:
        rx, ry = dog_data["position_x"], dog_data["position_y"]
        ryaw, roll, pitch = dog_data["sport_yaw"], dog_data["roll"], dog_data["pitch"]
        yaw_speed = dog_data["yaw_speed"]
    if rx is None or ry is None or ryaw is None:
        return
    if abs(roll or 0) > LIVE_MAP_MAX_TILT_RAD or abs(pitch or 0) > LIVE_MAP_MAX_TILT_RAD:
        return
    if abs(yaw_speed or 0) > LIVE_MAP_MAX_YAW_SPEED:
        # 2026-09-05, user visszajelzése: gyors forgás közben a nyers
        # odometria (nincs scan-matching/loop-closure) elcsúszik a valós
        # LiDAR-beeséssel szemben, és ugyanaz a fal 5-10 fokkal eltolva
        # újrarajzolódik — inkább kihagyjuk a frissítést, amíg lassul.
        return

    try:
        resp = requests.get(f"{HESAI_BRIDGE_URL}/lidar", timeout=1.0)
        points = resp.json() if resp.status_code == 200 else []
    except requests.RequestException:
        return
    if not points:
        return

    arr = np.asarray(points, dtype=np.float32)
    xyz = arr[:, :3].copy()
    roll, pitch = roll or 0.0, pitch or 0.0
    if roll or pitch:
        cr, sr = math.cos(-roll), math.sin(-roll)
        cp, sp = math.cos(-pitch), math.sin(-pitch)
        rx_m = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float32)
        ry_m = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float32)
        xyz = xyz @ rx_m.T @ ry_m.T

    z_mask = np.abs(xyz[:, 2]) <= LIVE_MAP_Z_BAND
    xyz = xyz[z_mask]
    if xyz.shape[0] == 0:
        return
    dist = np.hypot(xyz[:, 0], xyz[:, 1])
    range_mask = (dist >= LIVE_MAP_MIN_RANGE) & (dist <= LIVE_MAP_MAX_RANGE)
    xyz = xyz[range_mask]
    if xyz.shape[0] == 0:
        return

    world_yaw = ryaw + LIVE_MAP_YAW_OFFSET
    cos_y, sin_y = math.cos(world_yaw), math.sin(world_yaw)
    rot = np.array([[cos_y, -sin_y], [sin_y, cos_y]], dtype=np.float32)
    world_xy = xyz[:, :2] @ rot.T
    world_xy[:, 0] += rx
    world_xy[:, 1] += ry

    with _live_map_lock:
        st = _live_map_state
        res, ox, oy = st["resolution"], st["origin_x"], st["origin_y"]
        log_odds = st["log_odds"]

        # Ha a robot elhagyta a térkép területét (pl. áthelyezték másik helyszínre vagy >7m-re eltávolodott),
        # automatikusan újraközpontosítjuk a térképet a robot körül!
        cells = st["cells"]
        map_cx = ox + (cells * res) / 2.0
        map_cy = oy + (cells * res) / 2.0
        if log_odds is not None and math.hypot(rx - map_cx, ry - map_cy) > (LIVE_MAP_SIZE_M * 0.40):
            logger.info("Robot elhagyta a térkép területét (táv: %.1fm) — automatikus újraközpontosítás...", math.hypot(rx - map_cx, ry - map_cy))
            ox = rx - LIVE_MAP_SIZE_M / 2.0
            oy = ry - LIVE_MAP_SIZE_M / 2.0
            st["origin_x"] = ox
            st["origin_y"] = oy
            log_odds.fill(0)

        step = max(1, world_xy.shape[0] // 300)
        # A tényleges akkumulációs logika (log-odds Bresenham-frissítés +
        # a megjelenítendő tri-state rács újraszámolása) a lidar_mapping
        # modulban él, tesztelve szintetikus scan-ekkel — ld.
        # tests/test_lidar_mapping.py. `grid` itt egy ÚJ tömböt kap vissza,
        # ezért vissza is írjuk a state-be (nem lehet in-place módosítani
        # egy másik tömb tartalmát a régi referenciával).
        new_grid = lidar_mapping.integrate_scan(log_odds, rx, ry, world_xy[::step], ox, oy, res)
        st["grid"] = new_grid


def _live_map_thread():
    map_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mapping", "walk_seta1.map.json"))
    if os.path.exists(map_file):
        try:
            with open(map_file, "r") as mf:
                mdata = json.load(mf)
                with _live_map_lock:
                    st = _live_map_state
                    st["origin_x"] = mdata["origin_x"]
                    st["origin_y"] = mdata["origin_y"]
                    st["resolution"] = mdata["resolution"]
                    st["cells"] = mdata["width"]
                    st["grid"] = np.array(mdata["data"], dtype=np.int16).reshape((mdata["height"], mdata["width"]))
                    st["ready"] = True
                logger.info("Live map: loaded pre-recorded Hesai SLAM map %s (%dx%d)", map_file, mdata["width"], mdata["height"])
        except Exception as ex:
            logger.warning("Failed loading pre-recorded map: %s", ex)

    for _ in range(20):
        with _lock:
            rx0, ry0 = dog_data["position_x"], dog_data["position_y"]
        if rx0 is not None and ry0 is not None:
            break
        time.sleep(0.2)

    rx0 = rx0 if rx0 is not None else 0.0
    ry0 = ry0 if ry0 is not None else 0.0

    cells = int(LIVE_MAP_SIZE_M / LIVE_MAP_RESOLUTION)
    with _live_map_lock:
        st = _live_map_state
        if not st["ready"]:
            st["origin_x"] = rx0 - LIVE_MAP_SIZE_M / 2
            st["origin_y"] = ry0 - LIVE_MAP_SIZE_M / 2
            st["cells"] = cells
            st["grid"] = np.full((cells, cells), -1, dtype=np.int16)
            st["log_odds"] = np.zeros((cells, cells), dtype=np.float32)
            st["ready"] = True
    logger.info("Live map: ready=%s, origin=(%.2f, %.2f)", _live_map_state["ready"], _live_map_state["origin_x"], _live_map_state["origin_y"])

    while True:
        _live_map_update_once()
        _live_map_maybe_save_snapshot()
        time.sleep(0.5)


def _live_map_maybe_save_snapshot():
    """Every LIVE_MAP_SNAPSHOT_INTERVAL_S seconds, persists the current
    accumulated grid to disk as a PNG under static/maps/ — so the map
    survives a process restart (as an image, not resumable state) and can
    be inspected outside the live SSE stream. Failure is logged, never
    fatal (ld. lidar_mapping.save_grid_snapshot_png docstring)."""
    if not _live_map_snapshot_scheduler.due():
        return
    with _live_map_lock:
        st = _live_map_state
        grid = st["grid"]
        ready = st["ready"]
    if not ready or grid is None:
        return
    saved_path = lidar_mapping.save_grid_snapshot_png(grid, LIVE_MAP_SNAPSHOT_PATH)
    if saved_path is None:
        logger.warning("Live map: snapshot mentés sikertelen (%s)", LIVE_MAP_SNAPSHOT_PATH)
        return
    with _live_map_lock:
        _live_map_state["snapshot_url"] = "/static/maps/live_map.png"
        _live_map_state["snapshot_saved_at"] = time.time()


threading.Thread(target=_live_map_thread, daemon=True).start()


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

    def StopMove(self):
        self._log("StopMove")

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

    def FrontFlip(self):
        self._log("FrontFlip")

    def BackFlip(self):
        self._log("BackFlip")


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
        # 2026-09-09 FIX: swing > 0 esetén a comb előre lendül (a dőlésszög
        # csökken), nem hátrafelé — korábban +0.35 volt, ami miatt az avatár
        # hátrafelé lépkedett (RR/RL felé nyúlt a levegőben).
        thigh = _STAND_THIGH - 0.35 * swing
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
            mock_x, mock_y, mock_yaw = mock_streams.mock_position(t)
            dog_data["position_x"] = mock_x
            dog_data["position_y"] = mock_y
            dog_data["position_z"] = 0.0
            # sport_yaw = a position-nel egy "üzenetből" jövő, szinkron yaw
            # (ld. pose_snapshot kommentje) — a navigáció EZT használja, nem
            # az általános "yaw" mezőt.
            dog_data["sport_yaw"] = mock_yaw
            dog_data["motor_q"] = q
            dog_data["motor_tau"] = [
                round(3.0 + 4.0 * abs(math.sin(t * 4.0 + i)), 2) if walking else round(1.5 + 0.5 * math.sin(t + i), 2)
                for i in range(12)
            ]
            dog_data["motor_temp"] = [round(32 + 6 * (i % 3) + 2 * math.sin(t * 0.05 + i)) for i in range(12)]
            dog_data["mode_label"] = label
            dog_data["sport_state_time"] = time.time()
            dog_data["low_state_time"] = time.time()
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
                dog_data["low_state_time"] = time.time()

        def sport_state_handler(msg: SportModeState_):
            with _lock:
                dog_data["velocity_x"] = round(msg.velocity[0], 2)
                dog_data["velocity_y"] = round(msg.velocity[1], 2)
                dog_data["velocity_z"] = round(msg.velocity[2], 2)
                dog_data["yaw_speed"] = round(msg.yaw_speed, 2)
                # SportModeState_.position — a robot saját (VO/odometria-alapú)
                # abszolút pozíció-becslése, ld. unitree_sdk2py SportModeState_.
                # Ezt használjuk a saját (ROS-mentes) térkép-építő adat-dömperhez,
                # nem kell saját dead-reckoning integrálás.
                dog_data["position_x"] = round(msg.position[0], 3)
                dog_data["position_y"] = round(msg.position[1], 3)
                dog_data["position_z"] = round(msg.position[2], 3)
                # FONTOS a saját térkép-építőhöz: ezt a yaw-t (SportModeState_
                # SAJÁT imu_state-jéből, NEM a LowState_ külön DDS-üzenetéből)
                # használja a /pose_snapshot — a position és a yaw ugyanabból
                # az üzenetből jön, így nincs aszinkron csúszás a kettő közt
                # (a LowState_/SportModeState_ külön callback, külön ütemben
                # érkezik — forduláskor ez pár tized másodperces yaw/pozíció
                # csúszást okozott, ami a térképen szétkenődésként jelent meg).
                dog_data["sport_yaw"] = round(msg.imu_state.rpy[2], 3)
                dog_data["sport_state_time"] = time.time()

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
        "front_flip": sport_client.FrontFlip,
        "back_flip": sport_client.BackFlip,
    }


# Native SportClient acrobatics (ld. support.unitree.com Sports Services
# Interface — csak Go2 EDU, firmware <1.1.6). Nagy energiájú, eldöntetlen
# kimenetű mozdulat: rossz talaj/akku/tisztázatlan terep esetén a robot
# felboríthatja magát vagy megsérülhet a kamera/lidar tartó. Ezért NEM elég
# az általános armed-check — kell explicit megerősítés + akku-minimum.
_FLIP_ACTIONS = {"front_flip", "back_flip"}
_FLIP_MIN_VOLTAGE = 24.0  # 2026-09-17: óvatos becslés, nincs gyári min.-küszöb dokumentálva


@app.route("/pose_snapshot")
def pose_snapshot():
    """Egyszerű, nem-streamelő JSON-pillanatkép a robot pozíciójáról/orientációjáról
    — a saját (ROS-mentes) térkép-adat-dömper script ezt kérdezi le HTTP GET-tel,
    nem kell SSE-t parse-olnia.
    2026-09-09: t, sport_age_ms és low_age_ms hozzáadva a fáziskésés ellenőrzéséhez."""
    now = time.time()
    with _lock:
        st_time = dog_data.get("sport_state_time")
        lt_time = dog_data.get("low_state_time")
        return jsonify({
            "t": now,
            "position_x": dog_data["position_x"],
            "position_y": dog_data["position_y"],
            "position_z": dog_data["position_z"],
            # sport_yaw = SportModeState_ SAJÁT imu_state-je, ugyanabból az
            # üzenetből, mint a position — ezt kell használni térképezésnél,
            # NEM a "yaw" mezőt (az a külön LowState_ DDS-üzenetből jön,
            # aszinkron a position-nel, ld. sport_state_handler kommentje).
            "yaw": dog_data["sport_yaw"],
            "lowstate_yaw": dog_data["yaw"],
            "roll": dog_data["roll"],
            "pitch": dog_data["pitch"],
            "sport_age_ms": round((now - st_time) * 1000, 1) if st_time else None,
            "low_age_ms": round((now - lt_time) * 1000, 1) if lt_time else None,
            "sdk_ready": sdk_ready,
        })


@app.route("/sync_snapshot")
def sync_snapshot():
    """2026-09-09: Célzott diagnosztikai végpont — egyetlen atomi lekérdezésben
    adja vissza a pillanatnyi pozíciót, yaw-t, motor-szögeket és a legfrissebb
    Hesai LiDAR csomagot az időbélyegekkel együtt, a mintavételi aszinkronitás
    számszerű méréséhez."""
    now = time.time()
    with _lock:
        st_time = dog_data.get("sport_state_time")
        lt_time = dog_data.get("low_state_time")
        data = {
            "t": now,
            "position_x": dog_data["position_x"],
            "position_y": dog_data["position_y"],
            "position_z": dog_data["position_z"],
            "sport_yaw": dog_data["sport_yaw"],
            "lowstate_yaw": dog_data["yaw"],
            "roll": dog_data["roll"],
            "pitch": dog_data["pitch"],
            "yaw_speed": dog_data["yaw_speed"],
            "velocity_x": dog_data["velocity_x"],
            "motor_q": dog_data["motor_q"],
            "sport_age_ms": round((now - st_time) * 1000, 1) if st_time else None,
            "low_age_ms": round((now - lt_time) * 1000, 1) if lt_time else None,
            "sdk_ready": sdk_ready,
        }
    points = []
    try:
        resp = requests.get(f"{HESAI_BRIDGE_URL}/lidar", timeout=0.5)
        if resp.status_code == 200:
            points = resp.json()
    except Exception:
        pass
    data["lidar_points_count"] = len(points)
    data["lidar_points"] = points
    return jsonify(data)


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
                    "position_x": dog_data["position_x"],
                    "position_y": dog_data["position_y"],
                    "sport_yaw": dog_data["sport_yaw"],
                    "velocity_x": dog_data["velocity_x"],
                    "velocity_y": dog_data["velocity_y"],
                    "yaw_speed": dog_data["yaw_speed"],
                    "voltage": dog_data["voltage"],
                    "current": dog_data["current"],
                    "mode_label": dog_data["mode_label"],
                    "motor_names": MOTOR_NAMES,
                }
                payload["armed"] = _armed
                payload["sdk_ready"] = sdk_ready
                payload["data_source"] = DATA_SOURCE
            yield f"data: {json.dumps(payload)}\n\n"
            # 2026-09-05: 10 Hz -> 2 Hz — a böngésző fő szála túlterhelődött a
            # sok egyidejű SSE-stream + canvas-rajzolás miatt (ld. docs/15),
            # a kézi vezérlés gombjai emiatt nem reagáltak.
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/slam_data")
def slam_data():
    """SSE stream a valós SLAM-térképhez + robot-pózhoz (rosbridge-en
    keresztül, ld. _slam_bridge_thread) — 1 Hz, mert a térkép ritkán
    változik és a JSON-grid egyébként is nagy (width*height bájt)."""

    def generate():
        while True:
            with _slam_lock:
                payload = dict(_slam_state)
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/realsense_data")
def realsense_data():
    """SSE stream az Intel RealSense D435i szín-képéhez + mélység-pontfelhőhöz
    (ld. _realsense_bridge_thread) — 2 Hz, mert a pontfelhő is jelentős
    méretű JSON-t jelent."""

    def generate():
        while True:
            with _realsense_lock:
                payload = dict(_realsense_state)
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/realsense_feed")
def realsense_feed():
    """Intel RealSense D435i MJPEG videofolyam a rosbridge /camera/color/image_raw/compressed-ből."""
    import base64

    def generate():
        last_b64 = None
        while True:
            with _realsense_lock:
                b64 = _realsense_state.get("color_jpg_b64")
            if b64 and b64 != last_b64:
                last_b64 = b64
                try:
                    raw_jpg = base64.b64decode(b64)
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + raw_jpg + b"\r\n"
                    )
                except Exception:
                    pass
            time.sleep(0.04)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/realsense_depth_feed")
def realsense_depth_feed():
    """Intel RealSense D435i színezett 2D mélységtérkép MJPEG videofolyam."""
    import base64

    def generate():
        last_b64 = None
        while True:
            with _realsense_lock:
                b64 = _realsense_state.get("depth_jpg_b64")
            if b64 and b64 != last_b64:
                last_b64 = b64
                try:
                    raw_jpg = base64.b64decode(b64)
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + raw_jpg + b"\r\n"
                    )
                except Exception:
                    pass
            time.sleep(0.04)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


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


_mock_hesai_cache = []

def _load_mock_hesai():
    global _mock_hesai_cache
    if _mock_hesai_cache:
        return _mock_hesai_cache
    paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mapping", "walk_kicsi.jsonl")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mapping", "walk_seta1.jsonl")),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for idx, line in enumerate(f):
                        if idx > 150:
                            break
                        data = json.loads(line)
                        if "points" in data and data["points"]:
                            _mock_hesai_cache.append([[pt[0], pt[1], pt[2]] for pt in data["points"]])
                if _mock_hesai_cache:
                    logger.info("Loaded %d mock Hesai point cloud frames from %s", len(_mock_hesai_cache), p)
                    break
            except Exception as ex:
                logger.warning("Failed loading mock hesai: %s", ex)
    return _mock_hesai_cache


@app.route("/lidar_hesai_proxy")
def lidar_hesai_proxy():
    """A 2026-09-04-én felszerelt külső Hesai PandarXT-16 navigációs LiDAR
    pontfelhője, a hesai_bridge szolgáltatáson (:5003) keresztül."""
    limit = int(request.args.get("limit", "18000"))
    try:
        r = requests.get(f"{HESAI_BRIDGE_URL}/lidar?limit={limit}", timeout=1)
        if r.status_code == 200:
            return Response(r.content, status=r.status_code, mimetype="application/json")
    except requests.RequestException:
        pass

    frames = _load_mock_hesai()
    if frames:
        idx = int(time.time() * 5) % len(frames)
        pts = frames[idx][:limit]
        return jsonify(pts)
    return jsonify([])


@app.route("/api/hesai/spin_speed", methods=["GET", "POST"])
def api_hesai_spin_speed():
    """Hesai PandarXT-16 forgási frekvencia lekérdezése és állítása.
    Értékek: '1' = 300 rpm (5 Hz, 2x sűrűbb horizontális felbontás: 0.09-0.18 fok),
             '2' = 600 rpm (10 Hz, gyári alapértelmezett),
             '3' = 1200 rpm (20 Hz, ritkább mintavétel)."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = str(data.get("value", "1"))
        try:
            url = f"http://{HESAI_DEVICE_IP}/pandar.cgi?action=set&object=lidar&key=spin_speed&value={val}"
            r = requests.get(url, timeout=3)
            logger.info("Hesai forgási sebesség beállítva: %s -> HTTP %d", val, r.status_code)
            return jsonify({"status": "ok", "value": val, "response": r.json() if r.status_code == 200 else r.text})
        except Exception as e:
            logger.exception("Hiba a Hesai forgási sebesség beállításakor")
            return jsonify({"error": str(e)}), 502
    else:
        try:
            url = f"http://{HESAI_DEVICE_IP}/pandar.cgi?action=get&object=lidar_config"
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                body = r.json().get("Body", {})
                spin_speed = str(body.get("SpinSpeed", "1"))
                return jsonify({"status": "ok", "spin_speed": spin_speed})
            return jsonify({"status": "error", "code": r.status_code}), 502
        except Exception as e:
            logger.exception("Hiba a Hesai konfiguráció lekérdezésekor")
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


@app.route("/api/navigate", methods=["POST"])
def api_navigate():
    if not _is_armed():
        return jsonify({"error": "not armed"}), 403
    payload = request.get_json(force=True)
    with _nav_lock:
        if payload.get("queue"):
            queue = [{"x": float(p["x"]), "y": float(p["y"]), "action": p.get("action")} for p in payload["queue"]]
            _nav_state["target"] = queue.pop(0)
            _nav_state["queue"] = queue
        else:
            _nav_state["target"] = {"x": float(payload["x"]), "y": float(payload["y"]), "action": payload.get("action")}
            _nav_state["queue"] = []
        _nav_state["last_status"] = {"type": "started", "target": _nav_state["target"]}
        result = dict(_nav_state["target"])
    _touch_activity()
    return jsonify({"status": "ok", "target": result})


@app.route("/api/navigate/cancel", methods=["POST"])
def api_navigate_cancel():
    with _nav_lock:
        _nav_state["target"] = None
        _nav_state["queue"] = []
        _nav_state["last_status"] = {"type": "cancelled"}
    if sport_client:
        try:
            sport_client.Move(0, 0, 0)
        except Exception:
            logger.exception("navigate/cancel: Move(0,0,0) failed")
    return jsonify({"status": "cancelled"})


@app.route("/api/speak", methods=["POST"])
def api_speak():
    """Text-to-speech — offline synthesis (pyttsx3, ld. speech.py), a WAV
    hangot közvetlenül a válaszban adjuk vissza. NEM mozgásparancs (nem
    érinti a sport_client-et), ezért nincs armed-kapu rá, mint a
    /api/navigate-en — de minden hívást naplózunk, hogy nyomon követhető
    legyen, mit "mondott" a robot.

    FONTOS, hogy ne áltassuk magunkat: nincs megerősített fizikai
    hangszóró a roboton/dokkon (ld. speech.py docstringje és
    docs/18-tts-szoveg-felolvasas.md) — a WAV a böngészőben szólal meg,
    ami ezt a dashboardot nézi, nem a robotból."""
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "missing or empty 'text' field"}), 400

    logger.info("TTS request: %r", text[:200])
    audio = speech.speak_to_wav(text)
    if audio is None:
        return jsonify({
            "error": "tts unavailable (pyttsx3 not installed, or synthesis failed - see server logs)",
        }), 503
    return Response(audio, mimetype="audio/wav")


# Canned phrases hooked to a few mission actions — lightweight, best-effort:
# the /run_action route fires these in a background thread after the action
# itself starts, and never lets a TTS failure affect the action's own
# response (ld. run_action alul).
_ACTION_PHRASES = {
    "wave": "Szia!",
    "stand_up": "Talpra!",
}


@app.route("/api/estop", methods=["POST"])
def api_estop():
    """Vészleállító — megszakít minden futó autonóm scriptet (waypoint/
    follow-me/stb.), fixen kiküldi a Move(0,0,0)-t, és biztonság kedvéért
    disarmol is (a joystick/WASD is leáll, amíg valaki újra fel nem oldja)."""
    with _nav_lock:
        _nav_state["target"] = None
        _nav_state["queue"] = []
        _nav_state["last_status"] = {"type": "estop"}
    with _security_lock:
        _security_state["active"] = False
        _security_state["detected"] = False
        _security_state["bbox"] = None
    with _follow_lock:
        _follow_state["active"] = False
        _follow_state["detected"] = False
        _follow_state["bbox"] = None
        _follow_state["last_event"] = {"type": "estop", "t": time.time()}
    with _macro_lock:
        _macro_state["abort_flag"] = True
    if sport_client:
        try:
            sport_client.Move(0, 0, 0)
        except Exception:
            logger.exception("E-STOP: Move(0,0,0) failed")
    _set_armed(False)
    logger.warning("E-STOP triggered")
    return jsonify({"status": "estopped"})


@app.route("/api/security/start", methods=["POST"])
def security_start():
    with _security_lock:
        _security_state["active"] = True
    return jsonify({"status": "ok"})


@app.route("/api/security/stop", methods=["POST"])
def security_stop():
    with _security_lock:
        _security_state["active"] = False
        _security_state["detected"] = False
        _security_state["bbox"] = None
    if sport_client:
        try:
            sport_client.Move(0, 0, 0)
        except Exception:
            pass
    return jsonify({"status": "ok"})


@app.route("/security_status")
def security_status():
    with _security_lock:
        return jsonify(dict(_security_state))


@app.route("/api/follow/start", methods=["POST"])
def follow_start():
    """"Kövesd az embert" mód elindítása — ugyanaz az armed-kapu, mint a
    joystick/action gomboknál (ld. _is_armed()), mert ez a szál TÉNYLEGESEN
    mozgatja a robotot egy ember felé, felügyelet nélkül, amíg aktív."""
    if not _is_armed():
        return jsonify({"error": "not armed"}), 403
    with _follow_lock:
        if _follow_state["active"]:
            return jsonify({"status": "already running"})
        _follow_state["active"] = True
        _follow_state["detected"] = False
        _follow_state["bbox"] = None
        _follow_state["confidence"] = 0.0
        _follow_state["vx"] = 0.0
        _follow_state["vyaw"] = 0.0
        _follow_state["last_event"] = {"type": "started", "t": time.time()}
    threading.Thread(target=_follow_thread, daemon=True).start()
    _touch_activity()
    logger.info("Follow: elindítva")
    return jsonify({"status": "ok"})


@app.route("/api/follow/stop", methods=["POST"])
def follow_stop():
    with _follow_lock:
        was_active = _follow_state["active"]
        _follow_state["active"] = False
        _follow_state["detected"] = False
        _follow_state["bbox"] = None
        _follow_state["last_event"] = {"type": "stopped", "t": time.time()}
    if was_active:
        _safe_stop_move("Follow/stop")
    logger.info("Follow: leállítva")
    return jsonify({"status": "ok"})


@app.route("/follow_status")
def follow_status():
    with _follow_lock:
        return jsonify(dict(_follow_state))


_thermal_t0 = time.time()


@app.route("/api/thermal_stream")
def thermal_stream():
    """SSE stream az MLX90640 hőkamerához — 2 Hz, ld. mock_thermal.py.
    Ma este (MOCK_SDK=1) szimulált adat, holnap a valós EVB-board olvasás
    kerül a mock_thermal.get_thermal_frame() mögé, ez a végpont nem
    változik."""

    def generate():
        while True:
            frame = mock_thermal.get_thermal_frame(time.time() - _thermal_t0)
            if frame is None:
                payload = {"available": False}
            else:
                payload = {
                    "available": True,
                    "cols": mock_thermal.THERMAL_COLS,
                    "rows": mock_thermal.THERMAL_ROWS,
                    "data": frame,
                    "min": min(frame),
                    "max": max(frame),
                }
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1.0)  # 2026-09-05: ritkítva, ld. showcase_data komment

    return Response(generate(), mimetype="text/event-stream")


@app.route("/live_map_data")
def live_map_data():
    """SSE — az élő occupancy grid ("Robotporszívó mód"), ld.
    _live_map_thread. 1 Hz, mert a rács JSON-je jelentős méretű."""

    def generate():
        while True:
            with _live_map_lock:
                st = _live_map_state
                ready = st["ready"]
                grid = st["grid"]
                res, ox, oy = st["resolution"], st["origin_x"], st["origin_y"]
                snapshot_url, snapshot_saved_at = st["snapshot_url"], st["snapshot_saved_at"]
            with _lock:
                rx, ry, ryaw = dog_data["position_x"], dog_data["position_y"], dog_data["sport_yaw"]
            if ready and grid is not None:
                payload = {
                    "ready": True,
                    "width": int(grid.shape[1]),
                    "height": int(grid.shape[0]),
                    "resolution": res,
                    "origin_x": ox,
                    "origin_y": oy,
                    "data": grid.flatten().tolist(),
                    "robot_x": rx,
                    "robot_y": ry,
                    "robot_yaw": ryaw,
                    # 2026-09-17: a legutóbb diszkre mentett PNG-pillanatkép
                    # elérési útja/ideje — ld. _live_map_maybe_save_snapshot.
                    # A meglévő mezők (width/height/data/stb.) változatlanok,
                    # ez csak új, opcionális mező a meglévő fogyasztóknak.
                    "snapshot_url": snapshot_url,
                    "snapshot_saved_at": snapshot_saved_at,
                }
            else:
                payload = {"ready": False}
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1.0)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/nav_status")
def nav_status():
    with _nav_lock:
        return jsonify({
            "target": _nav_state["target"],
            "queue_len": len(_nav_state["queue"]),
            "last_status": _nav_state["last_status"],
        })


@app.route("/reset_map", methods=["POST"])
def reset_map():
    """Manuális térkép-újraközpontosítás az aktuális robot-pozíció körül."""
    with _lock:
        rx, ry = dog_data["position_x"], dog_data["position_y"]
    if rx is None or ry is None:
        return jsonify({"error": "nincs odometria adat"}), 400
    with _live_map_lock:
        st = _live_map_state
        cells = st.get("cells", int(LIVE_MAP_SIZE_M / LIVE_MAP_RESOLUTION))
        st["origin_x"] = rx - LIVE_MAP_SIZE_M / 2.0
        st["origin_y"] = ry - LIVE_MAP_SIZE_M / 2.0
        st["cells"] = cells
        if st.get("grid") is not None:
            st["grid"].fill(-1)
        if st.get("log_odds") is not None:
            st["log_odds"].fill(0)
        st["ready"] = True
    logger.info("Térkép manuálisan újraközpontosítva: origin=(%.2f, %.2f)", st["origin_x"], st["origin_y"])
    return jsonify({"success": True, "origin_x": st["origin_x"], "origin_y": st["origin_y"]})


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

    if action_name in _FLIP_ACTIONS:
        if (request.json or {}).get("confirm") is not True:
            return jsonify({"error": "flip requires explicit confirm:true in body — operator must clear terrain/clearance/spotter first"}), 400
        with _lock:
            voltage = dog_data.get("voltage")
        if voltage is not None and voltage < _FLIP_MIN_VOLTAGE:
            return jsonify({"error": f"battery too low for flip ({voltage}V < {_FLIP_MIN_VOLTAGE}V)"}), 409

    with _macro_lock:
        if _macro_state["recording"]:
            _macro_state["pending_action"] = action_name

    threading.Thread(target=action, daemon=True).start()
    _touch_activity()

    phrase = _ACTION_PHRASES.get(action_name)
    if phrase:
        # Best-effort, fire-and-forget: a TTS-hiba (hiányzó pyttsx3, stb.)
        # itt sose dobjon ki hibát az action-válaszból — speak_to_wav maga
        # sosem raise-el, de a szál indítását is óvatosan kezeljük.
        try:
            threading.Thread(target=speech.speak_to_wav, args=(phrase,), daemon=True).start()
        except Exception:
            logger.exception("run_action: failed to start TTS thread for %r", action_name)

    return jsonify({"status": f"running {action_name}"})


# --- Mission/task-queue routes (single Go2, ld. mission.py docstring) ----
@app.route("/api/mission", methods=["POST"])
def api_mission_submit():
    """Beküld egy waypoint+task listát ("queue"), de NEM indítja el —
    /api/mission/start külön hívás, hogy az operátor átnézhesse a tervet."""
    payload = request.get_json(force=True) or {}
    waypoints = payload.get("waypoints")
    if not waypoints:
        return jsonify({"error": "missing 'waypoints' list"}), 400
    try:
        cleaned = _mission_runner.submit(waypoints)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "submitted", "waypoints": cleaned})


@app.route("/api/mission/start", methods=["POST"])
def api_mission_start():
    """Elindítja a legutóbb beküldött missziót — háttérszálban fut, minden
    lépés előtt armed-checkkel, a mozgás a meglévő /api/navigate-mechanizmust
    használja (ld. _navigate_single)."""
    if not _is_armed():
        return jsonify({"error": "not armed"}), 403
    try:
        _mission_runner.start()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    _touch_activity()
    return jsonify({"status": "started"})


@app.route("/api/mission/cancel", methods=["POST"])
def api_mission_cancel():
    """Küldetés-megszakítás — azonnal leállítja a mozgást is (ugyanaz a
    Move(0,0,0)/StopMove fallback, mint /api/navigate/cancel-nél), a
    háttérszál a legközelebbi abort-ellenőrzésnél kilép."""
    _mission_runner.abort()
    return jsonify({"status": "aborted"})


@app.route("/mission_status")
def mission_status():
    return jsonify(_mission_runner.status())


# =====================================================================
# Mozgás Makró & Útvonal Rögzítő / Visszajátszó Végpontok (Macros API)
# =====================================================================

@app.route("/macro/record/start", methods=["POST"])
def macro_record_start():
    if not _is_armed():
        return jsonify({"error": "A robot nincs élesítve! Oldd fel (ARM) a felvétel előtt."}), 403
    payload = request.get_json(silent=True) or {}
    name = payload.get("name") or f"macro_{int(time.time())}"
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    if not safe_name:
        safe_name = f"macro_{int(time.time())}"

    with _macro_lock:
        _macro_state["recording"] = True
        _macro_state["record_start_t"] = time.time()
        _macro_state["record_name"] = safe_name
        _macro_state["samples"] = []
        _macro_state["waypoints"] = []
        _macro_state["pending_action"] = None
        _macro_state["play_progress"]["status"] = "recording"

    logger.info("Makró felvétel elindítva: %s", safe_name)
    return jsonify({"status": "recording_started", "name": safe_name})


@app.route("/macro/record/waypoint", methods=["POST"])
def macro_record_waypoint():
    payload = request.get_json(silent=True) or {}
    action_name = payload.get("action")
    with _lock:
        rx = dog_data.get("position_x")
        ry = dog_data.get("position_y")
        ryaw = dog_data.get("sport_yaw")

    with _macro_lock:
        t_rel = round(time.time() - _macro_state["record_start_t"], 2) if _macro_state["recording"] else 0.0
        wp = {
            "id": len(_macro_state["waypoints"]) + 1,
            "t": t_rel,
            "x": round(rx, 3) if rx is not None else 0.0,
            "y": round(ry, 3) if ry is not None else 0.0,
            "yaw": round(ryaw, 3) if ryaw is not None else 0.0,
            "action": action_name
        }
        _macro_state["waypoints"].append(wp)
        if _macro_state["recording"]:
            _macro_state["pending_action"] = f"waypoint:{wp['id']}"

    logger.info("Makró útpont rögzítve: #%d (x=%.2f, y=%.2f, yaw=%.2f)", wp["id"], wp["x"], wp["y"], wp["yaw"])
    return jsonify({"status": "ok", "waypoint": wp})


@app.route("/macro/record/stop", methods=["POST"])
def macro_record_stop():
    payload = request.get_json(silent=True) or {}
    custom_name = payload.get("name")
    with _macro_lock:
        if not _macro_state["recording"]:
            return jsonify({"error": "Nincs aktív felvétel"}), 400
        _macro_state["recording"] = False
        _macro_state["play_progress"]["status"] = "idle"
        name = custom_name or _macro_state["record_name"] or f"macro_{int(time.time())}"
        safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
        samples = list(_macro_state["samples"])
        waypoints = list(_macro_state["waypoints"])

    duration_s = round(samples[-1]["t"], 2) if samples else 0.0
    dist_m = 0.0
    for i in range(1, len(samples)):
        dx = samples[i]["x"] - samples[i-1]["x"]
        dy = samples[i]["y"] - samples[i-1]["y"]
        dist_m += math.hypot(dx, dy)

    macro_data = {
        "name": safe_name,
        "created_at": time.time(),
        "duration_s": duration_s,
        "distance_m": round(dist_m, 2),
        "sample_count": len(samples),
        "waypoint_count": len(waypoints),
        "samples": samples,
        "waypoints": waypoints
    }

    filepath = os.path.join(MACRO_DIR, f"{safe_name}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(macro_data, f, indent=2)
        logger.info("Makró sikeresen elmentve: '%s' (%s, %d minta, %.2f m)", safe_name, filepath, len(samples), dist_m)
    except Exception:
        logger.exception("Hiba a makró mentésekor: %s", safe_name)
        return jsonify({"error": "Hiba a makró fájl mentésekor"}), 500

    return jsonify({"status": "saved", "macro": {
        "name": safe_name,
        "duration_s": duration_s,
        "distance_m": round(dist_m, 2),
        "sample_count": len(samples),
        "waypoint_count": len(waypoints)
    }})


@app.route("/macro/list", methods=["GET"])
def macro_list():
    macros = []
    if os.path.exists(MACRO_DIR):
        for fname in os.listdir(MACRO_DIR):
            if fname.endswith(".json"):
                fpath = os.path.join(MACRO_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    macros.append({
                        "name": data.get("name", fname[:-5]),
                        "created_at": data.get("created_at", 0),
                        "duration_s": data.get("duration_s", 0.0),
                        "distance_m": data.get("distance_m", 0.0),
                        "sample_count": data.get("sample_count", len(data.get("samples", []))),
                        "waypoint_count": data.get("waypoint_count", len(data.get("waypoints", []))),
                    })
                except Exception:
                    logger.warning("Nem sikerült beolvasni a makró fájlt: %s", fname)
    macros.sort(key=lambda m: m["created_at"], reverse=True)
    return jsonify({"status": "ok", "macros": macros})


@app.route("/macro/get/<name>", methods=["GET"])
def macro_get(name):
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    fpath = os.path.join(MACRO_DIR, f"{safe_name}.json")
    if not os.path.exists(fpath):
        return jsonify({"error": "A makró nem található"}), 404
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"status": "ok", "macro": data})
    except Exception:
        logger.exception("Hiba a makró betöltésekor: %s", safe_name)
        return jsonify({"error": "Nem sikerült betölteni a makrót"}), 500


@app.route("/macro/delete/<name>", methods=["POST", "DELETE"])
def macro_delete(name):
    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    fpath = os.path.join(MACRO_DIR, f"{safe_name}.json")
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
            logger.info("Makró törölve: %s", safe_name)
            return jsonify({"status": "deleted", "name": safe_name})
        except Exception:
            logger.exception("Nem sikerült törölni a makrót: %s", safe_name)
            return jsonify({"error": "Törlési hiba"}), 500
    return jsonify({"error": "A makró nem található"}), 404


@app.route("/macro/play", methods=["POST"])
def macro_play():
    if not _is_armed():
        return jsonify({"error": "A robot nincs élesítve! Oldd fel (ARM) a kézi vezérlés panelen a lejátszáshoz."}), 403
    if not sport_client:
        return jsonify({"error": "Robot SDK kapcsolat nem elérhető!"}), 409

    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    speed = float(payload.get("speed", 0.5))

    if not name:
        return jsonify({"error": "Nincs makró kiválasztva!"}), 400

    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()
    fpath = os.path.join(MACRO_DIR, f"{safe_name}.json")
    if not os.path.exists(fpath):
        return jsonify({"error": f"A '{safe_name}' makró nem található!"}), 404

    with open(fpath, "r", encoding="utf-8") as f:
        macro_data = json.load(f)

    with _macro_lock:
        if _macro_state["playing"]:
            return jsonify({"error": "Már folyamatban van egy visszajátszás!"}), 409
        _macro_state["playing"] = True
        _macro_state["abort_flag"] = False

    t = threading.Thread(target=_macro_playback_worker, args=(macro_data, speed), daemon=True)
    t.start()
    with _macro_lock:
        _macro_state["play_thread"] = t

    _touch_activity()
    return jsonify({"status": "playing_started", "name": safe_name, "speed": speed})


@app.route("/macro/abort", methods=["POST"])
def macro_abort():
    with _macro_lock:
        _macro_state["abort_flag"] = True
    if sport_client:
        try:
            sport_client.Move(0, 0, 0)
        except Exception:
            pass
    logger.info("Makró visszajátszás manuálisan leállítva (/macro/abort)")
    return jsonify({"status": "aborted"})


@app.route("/macro/status", methods=["GET"])
def macro_status():
    with _macro_lock:
        return jsonify({
            "recording": _macro_state["recording"],
            "record_time": round(time.time() - _macro_state["record_start_t"], 1) if _macro_state["recording"] else 0.0,
            "sample_count": len(_macro_state["samples"]) if _macro_state["recording"] else 0,
            "waypoint_count": len(_macro_state["waypoints"]) if _macro_state["recording"] else 0,
            "playing": _macro_state["playing"],
            "play_macro_name": _macro_state["play_macro_name"],
            "progress": dict(_macro_state["play_progress"])
        })




if __name__ == "__main__":
    # threaded=True KRITIKUS: 4+ tartósan nyitott SSE-kapcsolat fut egyszerre
    # (showcase_data, slam_data, realsense_data, thermal_stream) — szálkezelés
    # nélkül a fejlesztői szerver egyetlen kapcsolatra korlátozódik, és az
    # /arm-hoz hasonló rövid POST-kérések percekig várakozhatnak a sorban.
    app.run(host="0.0.0.0", port=5002, threaded=True)
