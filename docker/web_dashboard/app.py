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

import mock_streams
import mock_thermal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nero_go2.web_dashboard")

app = Flask(__name__)

WEBRTC_BRIDGE_URL = os.environ.get("WEBRTC_BRIDGE_URL", "http://localhost:5001")
HESAI_BRIDGE_URL = os.environ.get("HESAI_BRIDGE_URL", "http://localhost:5003")

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
REALSENSE_ROSBRIDGE_HOST = os.environ.get("REALSENSE_ROSBRIDGE_HOST")
REALSENSE_ROSBRIDGE_PORT = int(os.environ.get("REALSENSE_ROSBRIDGE_PORT", "9091"))

_realsense_lock = threading.Lock()
_realsense_state = {
    "connected": False,
    "color_jpg_b64": None,  # a legutóbbi szín-képkocka, JPEG, base64-ben (közvetlenül <img src="data:...">-be tehető)
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

            color_topic = roslibpy.Topic(client, "/camera/color/image_raw/compressed", "sensor_msgs/CompressedImage")
            color_topic.subscribe(on_color)
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


# 2026-09-05, bemutató napja, user explicit biztonsági utasítása: a
# térképre kattintós navigáció (statikus, tegnapi mock-térképen!) NE
# mozgassa a valós robotot — a térkép nem a jelenlegi valós környezet,
# tehát a P-szabályozó vak lenne a tényleges akadályokra. A UI a tervezett
# útvonalat/fotó-akciót ettől függetlenül bemutatja, csak a Move() hívás
# marad ki. A robotot ma KIZÁRÓLAG a joystick/WASD mozgatja.
NAV_MOVE_ROBOT = False
NAV_SIMULATED_TRAVEL_S = 2.5  # ennyi "utazási időt" szimulálunk célpontonként


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


def _capture_photo():
    """Fényképező akciópont — kimenti az aktuális kamera-képkockát. MOCK
    módban (nincs webrtc_bridge lokálisan) egy előre elkészített kép-
    placeholder-t használ, hogy a frontend-lánc (SSE esemény -> oldalsáv
    -> térkép-bélyegkép) végigtesztelhető legyen ma este. Holnap reggel
    a webrtc_bridge már fut, a valós /camera.jpg-t menti."""
    filename = f"photo_{int(time.time())}.jpg"
    dest = os.path.join(os.path.dirname(__file__), "static", "photos", filename)
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
LOGODDS_HIT = 0.85
LOGODDS_MISS = -0.4
LOGODDS_MIN = -5.0
LOGODDS_MAX = 5.0
LOGODDS_OCC_THRESH = 2.0
LOGODDS_FREE_THRESH = -2.0

_live_map_lock = threading.Lock()
_live_map_state = {
    "ready": False,
    "grid": None,
    "log_odds": None,
    "resolution": LIVE_MAP_RESOLUTION,
    "origin_x": None,
    "origin_y": None,
    "cells": 0,
}


def _live_map_world_to_cell(wx, wy, origin_x, origin_y, resolution):
    return int((wx - origin_x) / resolution), int((wy - origin_y) / resolution)


def _bresenham_update_logodds(log_odds, x0, y0, x1, y1):
    """Saját, cv2-mentes vonal-rasterizálás (Bresenham-algoritmus) — a robot
    és egy LiDAR-pont közti cellákat "valószínűleg szabad" (LOGODDS_MISS),
    a végpontot (a tényleges visszaverődés helyét) "valószínűleg fal"
    (LOGODDS_HIT) irányba tolja, telítve [LOGODDS_MIN, LOGODDS_MAX] között."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    h, w = log_odds.shape
    x, y = x0, y0
    while True:
        if 0 <= x < w and 0 <= y < h:
            is_endpoint = (x == x1 and y == y1)
            delta = LOGODDS_HIT if is_endpoint else LOGODDS_MISS
            log_odds[y, x] = min(LOGODDS_MAX, max(LOGODDS_MIN, log_odds[y, x] + delta))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


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
        res, ox, oy, cells = st["resolution"], st["origin_x"], st["origin_y"], st["cells"]
        grid, log_odds = st["grid"], st["log_odds"]

        rcx, rcy = _live_map_world_to_cell(rx, ry, ox, oy, res)
        step = max(1, world_xy.shape[0] // 300)
        for wx, wy in world_xy[::step]:
            pcx, pcy = _live_map_world_to_cell(wx, wy, ox, oy, res)
            if 0 <= pcx < cells and 0 <= pcy < cells and 0 <= rcx < cells and 0 <= rcy < cells:
                _bresenham_update_logodds(log_odds, rcx, rcy, pcx, pcy)

        # A megjelenítendő rácsot a log-odds ALAPJÁN, minden tick-nél frissen
        # számoljuk ki (a log_odds maga a tartós, felhalmozódó állapot) — így
        # egy cella csak akkor válik "biztos fallá", ha a bizonyíték stabilan
        # afelé mutat, és NEM tud egyetlen kósza ponttól visszaugrálni.
        grid[:] = -1
        grid[log_odds >= LOGODDS_OCC_THRESH] = 100
        grid[log_odds <= LOGODDS_FREE_THRESH] = 0


def _live_map_thread():
    # Az induláskori pozíció körül fix méretű rácsot foglalunk le (nincs
    # dinamikus átméretezés — élő demóhoz elég, ld. build_map.py kommentje
    # a hasonló döntésről).
    while True:
        with _lock:
            rx0, ry0 = dog_data["position_x"], dog_data["position_y"]
        if rx0 is not None and ry0 is not None:
            break
        time.sleep(0.5)

    cells = int(LIVE_MAP_SIZE_M / LIVE_MAP_RESOLUTION)
    with _live_map_lock:
        st = _live_map_state
        st["origin_x"] = rx0 - LIVE_MAP_SIZE_M / 2
        st["origin_y"] = ry0 - LIVE_MAP_SIZE_M / 2
        st["cells"] = cells
        st["grid"] = np.full((cells, cells), -1, dtype=np.int16)
        st["log_odds"] = np.zeros((cells, cells), dtype=np.float32)
        st["ready"] = True
    logger.info("Live map: elindult, origin=(%.2f, %.2f), %dx%d cella", st["origin_x"], st["origin_y"], cells, cells)

    while True:
        _live_map_update_once()
        time.sleep(0.2)


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


@app.route("/pose_snapshot")
def pose_snapshot():
    """Egyszerű, nem-streamelő JSON-pillanatkép a robot pozíciójáról/orientációjáról
    — a saját (ROS-mentes) térkép-adat-dömper script ezt kérdezi le HTTP GET-tel,
    nem kell SSE-t parse-olnia."""
    with _lock:
        return jsonify({
            "position_x": dog_data["position_x"],
            "position_y": dog_data["position_y"],
            "position_z": dog_data["position_z"],
            # sport_yaw = SportModeState_ SAJÁT imu_state-je, ugyanabból az
            # üzenetből, mint a position — ezt kell használni térképezésnél,
            # NEM a "yaw" mezőt (az a külön LowState_ DDS-üzenetből jön,
            # aszinkron a position-nel, ld. sport_state_handler kommentje).
            "yaw": dog_data["sport_yaw"],
            "roll": dog_data["roll"],
            "pitch": dog_data["pitch"],
            "sdk_ready": sdk_ready,
        })


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


@app.route("/lidar_hesai_proxy")
def lidar_hesai_proxy():
    """A 2026-09-04-én felszerelt külső Hesai PandarXT-16 navigációs LiDAR
    pontfelhője, a hesai_bridge szolgáltatáson (:5003) keresztül."""
    try:
        r = requests.get(f"{HESAI_BRIDGE_URL}/lidar", timeout=2)
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
    # threaded=True KRITIKUS: 4+ tartósan nyitott SSE-kapcsolat fut egyszerre
    # (showcase_data, slam_data, realsense_data, thermal_stream) — szálkezelés
    # nélkül a fejlesztői szerver egyetlen kapcsolatra korlátozódik, és az
    # /arm-hoz hasonló rövid POST-kérések percekig várakozhatnak a sorban.
    app.run(host="0.0.0.0", port=5002, threaded=True)
