"""Egyrobot (Go2-only) küldetés/task-queue futtató.

Szándékosan NEM multi-robot — ld. TODO.md "Multi-robot core refaktor" szakasza:
a Xavier Pickerbot + Go2 közös mission-control/core/service.py csak akkor épülhet
meg, ha az a refaktor előbb megtörténik. Ez a modul addig kizárólag egy darab
Go2-t vezérel, és a meglévő app.py navigate/action primitíveket használja fel —
SOHA nem hívja közvetlenül a sport_client-et.

Dependency injection: a MissionRunner semmit nem tud a Flaskről, a DDS-ről vagy
a sport_client-ről — csak a neki átadott függvényeket hívja. Ez két okból
fontos:
  1. Minden mozgás-parancs az app.py-ban MÁR meglévő armed/watchdog/E-stop
     kapun megy át (is_armed_fn + navigate_to_fn = _navigate_single, ami
     ugyanazt az _nav_state-et írja, mint az /api/navigate route) — a
     mission-runner nem tud "megkerülni" semmit, mert nincs saját mozgás-útja.
  2. Unit tesztelhető hardware/Flask nélkül, sima Python-függvényekkel.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("nero_go2.mission")

VALID_TASKS = {"pose", "photo", "lie_down", "charge_dock"}

NAV_POLL_INTERVAL_S = 0.2
# Egy célpont elérésének max. ideje, mielőtt a missziót hibásnak jelöljük és
# leállítjuk — anélkül egy elakadt robot a küldetést örökre "running"-ban
# tartaná.
NAV_WAYPOINT_TIMEOUT_S = 60.0


class MissionRunner:
    """Egy misszió (waypoint+task sor) állapota és háttérszál-futtatója.

    Státuszgép: idle -> running -> (done | aborted | error). submit() mindig
    idle-be reset, start() csak idle-ből futtatható, abort() bármikor hívható.
    """

    def __init__(
        self,
        is_armed_fn,
        navigate_to_fn,
        cancel_navigate_fn,
        nav_reached_fn,
        run_pose_action_fn,
        capture_photo_fn,
        lie_down_fn,
        charge_dock_fn=None,
    ):
        self._is_armed_fn = is_armed_fn
        self._navigate_to_fn = navigate_to_fn
        self._cancel_navigate_fn = cancel_navigate_fn
        self._nav_reached_fn = nav_reached_fn
        self._run_pose_action_fn = run_pose_action_fn
        self._capture_photo_fn = capture_photo_fn
        self._lie_down_fn = lie_down_fn
        self._charge_dock_fn = charge_dock_fn or self._default_charge_dock_stub

        self._lock = threading.Lock()
        self._abort_event = threading.Event()
        self._thread = None
        self._state = {
            "status": "idle",  # idle | running | done | aborted | error
            "waypoints": [],
            "current_index": None,
            "results": [],
            "error": None,
        }

    # ---------------------------------------------------------------- API --
    def submit(self, waypoints):
        """Beküld egy új waypoint-listát. Nem indítja el — start() külön hívás,
        hogy az operátor átnézhesse a tervezett útvonalat, mielőtt a robot
        elindul."""
        if not waypoints:
            raise ValueError("üres waypoint-lista")
        cleaned = []
        for i, wp in enumerate(waypoints):
            task = wp.get("task")
            if task not in VALID_TASKS:
                raise ValueError(
                    f"ismeretlen task '{task}' a {i}. waypointnál "
                    f"(engedélyezett: {sorted(VALID_TASKS)})"
                )
            cleaned.append(
                {
                    "id": wp.get("id", i),
                    "x": float(wp["x"]),
                    "y": float(wp["y"]),
                    "task": task,
                    "task_param": wp.get("task_param"),
                }
            )
        with self._lock:
            if self._state["status"] == "running":
                raise RuntimeError("már fut egy misszió — előbb abort()")
            self._state = {
                "status": "idle",
                "waypoints": cleaned,
                "current_index": None,
                "results": [],
                "error": None,
            }
        return cleaned

    def start(self):
        with self._lock:
            if self._state["status"] == "running":
                raise RuntimeError("már fut egy misszió")
            if not self._state["waypoints"]:
                raise RuntimeError("nincs beküldött misszió (submit() előbb)")
            self._state["status"] = "running"
            self._state["current_index"] = 0
            self._state["results"] = []
            self._state["error"] = None
        self._abort_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def abort(self):
        """Azonnal leállítja a küldetést ÉS a mozgást is (cancel_navigate_fn) —
        ezt a state-gépen kívül, szinkron hívjuk, hogy a robot akkor is
        megálljon, ha a futó szál éppen egy hosszú alvásban/várakozásban van."""
        self._abort_event.set()
        try:
            self._cancel_navigate_fn()
        except Exception:
            logger.exception("mission.abort: cancel_navigate_fn failed")
        with self._lock:
            if self._state["status"] == "running":
                self._state["status"] = "aborted"

    def status(self):
        with self._lock:
            return {
                "status": self._state["status"],
                "waypoints": list(self._state["waypoints"]),
                "current_index": self._state["current_index"],
                "results": list(self._state["results"]),
                "error": self._state["error"],
            }

    def join(self, timeout=None):
        """Csak tesztekhez/CLI-hez — megvárja a háttérszál befejezését."""
        if self._thread is not None:
            self._thread.join(timeout)

    # ----------------------------------------------------------- internal --
    def _default_charge_dock_stub(self, waypoint):
        logger.info(
            "charge_dock stub: would dock here (waypoint id=%s, x=%.2f, y=%.2f) "
            "— nincs valós dokkoló-station integráció ebben a repóban",
            waypoint["id"],
            waypoint["x"],
            waypoint["y"],
        )
        return {
            "ok": False,
            "note": "would dock here (stub — no real docking-station integration exists)",
        }

    def _run(self):
        waypoints = self.status()["waypoints"]
        for idx, wp in enumerate(waypoints):
            if self._abort_event.is_set():
                self._finish("aborted")
                return

            with self._lock:
                self._state["current_index"] = idx

            if not self._is_armed_fn():
                logger.warning(
                    "mission: disarmed a %s. waypoint (id=%s) előtt, misszió leáll",
                    idx,
                    wp["id"],
                )
                self._finish("aborted", error="disarmed mid-mission")
                return

            try:
                self._navigate_to_fn(wp["x"], wp["y"])
            except Exception:
                logger.exception("mission: navigate_to_fn failed at waypoint %s", wp["id"])
                self._finish("error", error=f"navigate failed at waypoint {wp['id']}")
                return

            if not self._wait_for_arrival(wp):
                return  # _wait_for_arrival már beállította a végállapotot

            if self._abort_event.is_set():
                self._finish("aborted")
                return
            if not self._is_armed_fn():
                logger.warning(
                    "mission: disarmed a %s. waypoint (id=%s) task-ja előtt, misszió leáll",
                    idx,
                    wp["id"],
                )
                self._finish("aborted", error="disarmed mid-mission")
                return

            result = self._execute_task(wp)
            with self._lock:
                self._state["results"].append(result)

        self._finish("done")

    def _wait_for_arrival(self, wp):
        deadline = time.time() + NAV_WAYPOINT_TIMEOUT_S
        while time.time() < deadline:
            if self._abort_event.is_set():
                self._finish("aborted")
                return False
            try:
                reached = self._nav_reached_fn(wp["x"], wp["y"])
            except Exception:
                logger.exception("mission: nav_reached_fn failed at waypoint %s", wp["id"])
                self._finish("error", error=f"nav_reached_fn failed at waypoint {wp['id']}")
                return False
            if reached:
                return True
            time.sleep(NAV_POLL_INTERVAL_S)
        logger.warning("mission: waypoint %s elérése timeout (%ss)", wp["id"], NAV_WAYPOINT_TIMEOUT_S)
        self._finish("error", error=f"waypoint {wp['id']} timeout")
        return False

    def _execute_task(self, wp):
        task = wp["task"]
        try:
            if task == "pose":
                self._run_pose_action_fn(wp.get("task_param") or "sit")
                return {"task": task, "ok": True, "waypoint_id": wp["id"]}
            if task == "photo":
                path = self._capture_photo_fn(wp["id"])
                return {
                    "task": task,
                    "ok": path is not None,
                    "waypoint_id": wp["id"],
                    "photo_url": path,
                }
            if task == "lie_down":
                self._lie_down_fn()
                return {"task": task, "ok": True, "waypoint_id": wp["id"]}
            if task == "charge_dock":
                res = dict(self._charge_dock_fn(wp))
                res["task"] = task
                res["waypoint_id"] = wp["id"]
                # Sose engedjük, hogy a charge_dock task "ok": True-t adjon
                # vissza — a stub nem tud tényleges dokkolást igazolni, mivel
                # nincs valós dokkoló-station integráció (ld. modul docstring).
                res["ok"] = False
                return res
        except Exception:
            logger.exception("mission: task '%s' failed at waypoint %s", task, wp["id"])
            return {"task": task, "ok": False, "waypoint_id": wp["id"], "error": "task execution failed"}
        return {"task": task, "ok": False, "waypoint_id": wp["id"], "error": "unknown task"}

    def _finish(self, status, error=None):
        with self._lock:
            self._state["status"] = status
            if error:
                self._state["error"] = error
