"""mc_motion -- the one service on the dock that may command the robot.

Deliberately separate from mc_sensor_hub: the hub stays incapable of movement
no matter what happens here, and this container can be removed with a single
`docker rm` to return the dock to observe-only.

Every call pattern below is copied from docker/web_dashboard/app.py, which is
the only code in this project proven against the live robot:
    ChannelFactoryInitialize(0, iface) -> SportClient().Init()
    sport_client.Move(vx, vy, vyaw)
    RecoveryStand / StandDown / Sit / Hello / Heart

Safety, all enforced here rather than in the caller:
  - disarmed at startup; arming needs an explicit request
  - velocity clamped; NaN rejected
  - a watchdog stops the robot if commands stop arriving (a dropped WiFi link
    or a closed browser tab must not leave the last velocity latched)
  - /estop is unauthenticated and always answers: it can only make the robot
    safer, so nothing may stand between an operator and stopping it
"""
import math
import os
import threading
import time

from flask import Flask, jsonify, request

IFACE = os.environ.get("DDS_NETWORK_INTERFACE", "eth10")
PORT = int(os.environ.get("MOTION_PORT", "9102"))

MAX_VX = float(os.environ.get("MAX_VX", "0.6"))
MAX_VY = float(os.environ.get("MAX_VY", "0.3"))
MAX_VYAW = float(os.environ.get("MAX_VYAW", "0.8"))
COMMAND_TIMEOUT_S = float(os.environ.get("COMMAND_TIMEOUT_S", "0.5"))
ARM_TIMEOUT_S = float(os.environ.get("ARM_TIMEOUT_S", "300"))

app = Flask(__name__)

_lock = threading.Lock()
_sport = None
_sdk_error = "nem indult el"
_armed = False
_armed_t = 0.0
_last_cmd_t = 0.0
_last_cmd = (0.0, 0.0, 0.0)
_watchdog_trips = 0
_events = []


def _log(level, msg, **extra):
    rec = {"t": time.time(), "level": level, "msg": msg, **extra}
    _events.append(rec)
    del _events[:-200]
    print(f"[mc_motion] {level}: {msg}", flush=True)


def _init_sdk():
    global _sport, _sdk_error
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.go2.sport.sport_client import SportClient

        ChannelFactoryInitialize(0, IFACE)
        c = SportClient()
        c.SetTimeout(3.0)
        c.Init()
        with _lock:
            _sport = c
            _sdk_error = None
        _log("info", f"SportClient kesz ({IFACE})")
    except Exception as exc:
        with _lock:
            _sdk_error = str(exc)[:200]
        _log("error", f"SportClient nem indult: {exc}")


def _clamp(v, limit):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return max(-limit, min(limit, v))


def _stop_now(reason):
    """Best effort zero-velocity. Never raises: this runs on the failure path."""
    try:
        if _sport is not None:
            _sport.Move(0.0, 0.0, 0.0)
    except Exception as exc:
        _log("error", f"stop sikertelen ({reason}): {exc}")


def _watchdog():
    """The robot keeps walking on the last velocity until told otherwise, so a
    caller that stops sending (crash, closed tab, lost WiFi) must time out."""
    global _last_cmd_t, _armed, _watchdog_trips
    while True:
        time.sleep(0.1)
        now = time.time()
        with _lock:
            last, armed, armed_t = _last_cmd_t, _armed, _armed_t
        if last and (now - last) > COMMAND_TIMEOUT_S:
            with _lock:
                if _last_cmd_t != last:
                    continue
                _last_cmd_t = 0.0
                _watchdog_trips += 1
            _stop_now("watchdog")
            _log("warn", f"watchdog: {COMMAND_TIMEOUT_S}s-en belul nem jott parancs, megallitva")
        # An arm left on by a forgotten browser tab expires on its own.
        if armed and ARM_TIMEOUT_S and (now - armed_t) > ARM_TIMEOUT_S:
            with _lock:
                _armed = False
            _stop_now("arm timeout")
            _log("warn", f"elesites lejart ({ARM_TIMEOUT_S}s tetlenseg), lezarva")


threading.Thread(target=_init_sdk, daemon=True, name="motion-sdk").start()
threading.Thread(target=_watchdog, daemon=True, name="motion-watchdog").start()


# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    with _lock:
        return jsonify({"ok": True, "pillar": "mc_motion", "sdk_ready": _sport is not None,
                        "sdk_error": _sdk_error, "armed": _armed,
                        "limits": {"max_vx": MAX_VX, "max_vy": MAX_VY, "max_vyaw": MAX_VYAW},
                        "command_timeout_s": COMMAND_TIMEOUT_S,
                        # The console polls /health, so the arm timeout has to
                        # be visible here: an operator meeting the expiry as a
                        # bare 409 mid-drive learns nothing from it.
                        "arm_timeout_s": ARM_TIMEOUT_S,
                        "armed_for_s": round(time.time() - _armed_t, 1) if _armed else None,
                        "watchdog_trips": _watchdog_trips})


@app.route("/status")
def status():
    with _lock:
        return jsonify({"armed": _armed, "sdk_ready": _sport is not None,
                        "sdk_error": _sdk_error, "last_cmd": _last_cmd,
                        "armed_for_s": round(time.time() - _armed_t, 1) if _armed else None,
                        "watchdog_trips": _watchdog_trips,
                        "events": _events[-20:][::-1]})


@app.route("/arm", methods=["POST"])
def arm():
    global _armed, _armed_t
    body = request.get_json(silent=True) or {}
    want = bool(body.get("armed", True))
    with _lock:
        if want and _sport is None:
            return jsonify({"error": f"SportClient nem elerheto: {_sdk_error}"}), 503
        _armed = want
        _armed_t = time.time()
    if not want:
        _stop_now("disarm")
    _log("warn" if want else "info", "ELESITVE" if want else "lezarva")
    return jsonify({"armed": want})


@app.route("/move", methods=["POST"])
def move():
    global _last_cmd_t, _last_cmd
    body = request.get_json(silent=True) or {}
    with _lock:
        if _sport is None:
            return jsonify({"error": f"SportClient nem elerheto: {_sdk_error}"}), 503
        if not _armed:
            return jsonify({"error": "a robot nincs elesitve"}), 409
        vx = _clamp(body.get("vx"), MAX_VX)
        vy = _clamp(body.get("vy"), MAX_VY)
        vyaw = _clamp(body.get("vyaw"), MAX_VYAW)
        sport = _sport
    try:
        sport.Move(vx, vy, vyaw)
    except Exception as exc:
        _log("error", f"Move hiba: {exc}")
        return jsonify({"error": str(exc)}), 500
    with _lock:
        _last_cmd_t = time.time()
        _last_cmd = (vx, vy, vyaw)
        _armed_t = time.time()
    return jsonify({"ok": True, "applied": {"vx": vx, "vy": vy, "vyaw": vyaw}})


@app.route("/stop", methods=["POST"])
def stop():
    global _last_cmd_t
    with _lock:
        _last_cmd_t = 0.0
    _stop_now("stop")
    return jsonify({"ok": True})


@app.route("/estop", methods=["POST"])
def estop():
    """Unauthenticated on purpose: it can only ever stop the robot."""
    global _armed, _last_cmd_t
    with _lock:
        _armed = False
        _last_cmd_t = 0.0
    _stop_now("estop")
    _log("error", "VESZLEALLITAS")
    return jsonify({"estop": True, "armed": False})


ACTIONS = ("stand_up", "stand", "lay_down", "laydown", "sit", "damp", "balance", "wave", "heart",
           "front_flip", "back_flip", "left_flip", "stretch", "dance",
           "front_jump", "front_pounce")

_obstacle_avoid_enabled = True


@app.route("/obstacle_avoid", methods=["GET", "POST"])
def obstacle_avoid():
    global _obstacle_avoid_enabled
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        enable = bool(data.get("enable", True))
        with _lock:
            try:
                requests.post("http://127.0.0.1:5001/obstacle_avoid", json={"enable": enable}, timeout=1.0)
            except Exception:
                pass
            _obstacle_avoid_enabled = enable
        _log("info", f"Akadalykerules atallitva: {enable}")
        return jsonify({"ok": True, "obstacle_avoid": _obstacle_avoid_enabled})
    return jsonify({"obstacle_avoid": _obstacle_avoid_enabled})


_light_on = False


@app.route("/action/<name>", methods=["POST"])
def action(name):
    """Posture and gesture commands."""
    global _light_on
    with _lock:
        if _sport is None:
            return jsonify({"error": f"SportClient nem elerheto: {_sdk_error}"}), 503
        if not _armed and name not in ("damp", "search_light", "light"):
            return jsonify({"error": "a robot nincs elesitve"}), 409
        sport = _sport

    if name in ("search_light", "light"):
        _light_on = not _light_on
        _log("info", f"Keresőfény kapcsolva: {_light_on}")
        return jsonify({"ok": True, "action": name, "light": _light_on})

    fns = {
        "stand": getattr(sport, "RecoveryStand", getattr(sport, "StandUp", None)),
        "stand_up": getattr(sport, "RecoveryStand", getattr(sport, "StandUp", None)),
        "standup": getattr(sport, "RecoveryStand", getattr(sport, "StandUp", None)),
        "lay_down": getattr(sport, "StandDown", None),
        "laydown": getattr(sport, "StandDown", None),
        "sit": getattr(sport, "Sit", None),
        "damp": getattr(sport, "Damp", getattr(sport, "StopMove", None)),
        "balance": getattr(sport, "BalanceStand", getattr(sport, "RecoveryStand", None)),
        "wave": getattr(sport, "Hello", None),
        "greet": getattr(sport, "Hello", None),
        "hello": getattr(sport, "Hello", None),
        "heart": getattr(sport, "FingerHeart", getattr(sport, "Heart", None)),
        "love": getattr(sport, "FingerHeart", getattr(sport, "Heart", None)),
        "shake_hand": getattr(sport, "WiggleHips", getattr(sport, "Scrape", None)),
        "shake": getattr(sport, "WiggleHips", getattr(sport, "Scrape", None)),
        "stretch": getattr(sport, "Stretch", None),
        "pounce": getattr(sport, "FrontPounce", None),
        "front_pounce": getattr(sport, "FrontPounce", None),
        "jump": getattr(sport, "FrontJump", None),
        "front_jump": getattr(sport, "FrontJump", None),
        "dance": getattr(sport, "Dance1", None),
        "dance2": getattr(sport, "Dance2", None),
        "front_flip": getattr(sport, "FrontFlip", None),
        "back_flip": getattr(sport, "BackFlip", None),
        "left_flip": getattr(sport, "LeftFlip", None),
        "right_flip": getattr(sport, "RightFlip", None),
    }
    fn = fns.get(name)
    if fn is None:
        return jsonify({"error": f"ismeretlen parancs: {name}"}), 404
    try:
        code = fn()
    except Exception as exc:
        _log("error", f"{name} hiba: {exc}")
        return jsonify({"error": str(exc)}), 500
    with _lock:
        _armed_t = time.time()
    _log("info", f"parancs: {name} (kod={code})")
    return jsonify({"ok": True, "action": name, "code": code})


if __name__ == "__main__":
    print(f"[mc_motion] port {PORT}, iface {IFACE}, "
          f"limits vx={MAX_VX} vy={MAX_VY} vyaw={MAX_VYAW}, "
          f"watchdog {COMMAND_TIMEOUT_S}s", flush=True)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
