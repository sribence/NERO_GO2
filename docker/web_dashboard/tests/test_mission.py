"""Egyrobot (Go2-only) mission/task-queue tesztek.

A MissionRunner (mission.py) semmit nem tud a Flaskről/DDS-ről/sport_client-ről
— minden mozgás/task egy injektált függvényen megy át. Ez a teszt-fájl ezért
egy sima Python fake-en (FakeRig) keresztül ellenőrzi a viselkedést, ami
pontosan azt a helyzetet modellezi, amit app.py MOCK_SDK=1 alatt bekötne:
armed-state, egypontos navigáció + "megérkezett" jelzés, task-végrehajtás.

Fedett esetek (ld. task-leírás):
  1. a küldetés waypointonként halad (mocked/no-hardware módban)
  2. abort a küldetés közben TÉNYLEG megállítja a további waypointokat
  3. a charge_dock stub SOHA nem állít olyan sikert, amit nem tud igazolni
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mission  # noqa: E402


def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class FakeRig:
    """Modellezi az app.py MOCK_SDK=1 alatti navigate/action rétegét: egy
    célpont "megérkezettnek" számít N poll-ellenőrzés után (ld.
    arrivals_after), az armed-flag bármikor kikapcsolható a teszt által, a
    task-végrehajtók pedig csak feljegyzik a hívást."""

    def __init__(self, arrivals_after=1):
        self.armed = True
        self.arrivals_after = arrivals_after
        self.target = None
        self._checks_for_target = 0
        self.navigate_calls = []
        self.cancel_calls = 0
        self.pose_calls = []
        self.photo_calls = []
        self.lie_down_calls = 0

    # ---- navigate mechanizmus (a mission.py ezt injektálja) ----
    def is_armed(self):
        return self.armed

    def navigate_to(self, x, y):
        if not self.armed:
            raise RuntimeError("not armed")
        self.navigate_calls.append((x, y))
        self.target = (x, y)
        self._checks_for_target = 0

    def cancel(self):
        self.cancel_calls += 1
        self.target = None

    def reached(self, x, y):
        if self.target != (x, y):
            return False
        self._checks_for_target += 1
        if self._checks_for_target >= self.arrivals_after:
            self.target = None
            return True
        return False

    # ---- task-végrehajtók ----
    def run_pose(self, action_name):
        if not self.armed:
            raise RuntimeError("not armed")
        self.pose_calls.append(action_name)

    def capture_photo(self, waypoint_id):
        self.photo_calls.append(waypoint_id)
        return f"/static/photos/photo_wp{waypoint_id}.jpg"

    def lie_down(self):
        if not self.armed:
            raise RuntimeError("not armed")
        self.lie_down_calls += 1


def make_runner(rig, **overrides):
    kwargs = dict(
        is_armed_fn=rig.is_armed,
        navigate_to_fn=rig.navigate_to,
        cancel_navigate_fn=rig.cancel,
        nav_reached_fn=rig.reached,
        run_pose_action_fn=rig.run_pose,
        capture_photo_fn=rig.capture_photo,
        lie_down_fn=rig.lie_down,
    )
    kwargs.update(overrides)
    return mission.MissionRunner(**kwargs)


WAYPOINTS = [
    {"id": "a", "x": 1.0, "y": 0.0, "task": "pose", "task_param": "wave"},
    {"id": "b", "x": 2.0, "y": 0.0, "task": "photo"},
    {"id": "c", "x": 3.0, "y": 0.0, "task": "lie_down"},
]


def test_mission_advances_waypoint_by_waypoint_in_mock_mode():
    rig = FakeRig(arrivals_after=1)
    runner = make_runner(rig)
    runner.submit(WAYPOINTS)
    runner.start()

    assert _wait_until(lambda: runner.status()["status"] in ("done", "aborted", "error"))

    status = runner.status()
    assert status["status"] == "done", status
    assert rig.navigate_calls == [(1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    assert rig.pose_calls == ["wave"]
    assert rig.photo_calls == ["b"]
    assert rig.lie_down_calls == 1

    results = status["results"]
    assert [r["waypoint_id"] for r in results] == ["a", "b", "c"]
    assert [r["task"] for r in results] == ["pose", "photo", "lie_down"]
    assert all(r["ok"] for r in results)


def test_mission_status_tracks_current_index_while_running():
    rig = FakeRig(arrivals_after=5)  # elég lassú, hogy elkapjuk "running"-ban
    runner = make_runner(rig)
    runner.submit(WAYPOINTS)
    runner.start()

    assert _wait_until(lambda: runner.status()["current_index"] == 0)
    assert runner.status()["status"] == "running"

    runner.abort()
    runner.join(timeout=5.0)


def test_abort_mid_mission_stops_further_waypoints():
    rig = FakeRig(arrivals_after=1000)  # az első waypoint sosem "érkezik meg"
    runner = make_runner(rig)
    runner.submit(WAYPOINTS)
    runner.start()

    assert _wait_until(lambda: rig.navigate_calls == [(1.0, 0.0)])
    runner.abort()
    runner.join(timeout=5.0)

    status = runner.status()
    assert status["status"] == "aborted"
    # csak az ELSŐ waypointra navigált — a b/c-re sose ment ki a Move-parancs
    assert rig.navigate_calls == [(1.0, 0.0)]
    assert rig.cancel_calls >= 1
    assert rig.pose_calls == []
    assert rig.photo_calls == []
    assert rig.lie_down_calls == 0
    assert status["results"] == []


def test_disarm_mid_mission_stops_immediately_without_pushing_through():
    rig = FakeRig(arrivals_after=1)
    runner = make_runner(rig)

    # az "a" waypoint pose-task-ja alatt disarmol — a "b"-re NEM szabad kimenni
    original_run_pose = rig.run_pose

    def run_pose_then_disarm(action_name):
        original_run_pose(action_name)
        rig.armed = False

    runner = make_runner(rig, run_pose_action_fn=run_pose_then_disarm)
    runner.submit(WAYPOINTS)
    runner.start()

    assert _wait_until(lambda: runner.status()["status"] in ("done", "aborted", "error"))

    status = runner.status()
    assert status["status"] == "aborted"
    assert status["error"] == "disarmed mid-mission"
    # "a" lefutott (armed volt még), de "b"-re már nem navigált
    assert rig.navigate_calls == [(1.0, 0.0)]
    assert rig.photo_calls == []
    assert rig.lie_down_calls == 0


def test_charge_dock_stub_never_claims_success_it_cannot_back_up(caplog):
    rig = FakeRig(arrivals_after=1)
    runner = make_runner(rig)
    runner.submit([{"id": "dock1", "x": 5.0, "y": 5.0, "task": "charge_dock"}])
    runner.start()

    assert _wait_until(lambda: runner.status()["status"] in ("done", "aborted", "error"))

    status = runner.status()
    assert status["status"] == "done"
    assert len(status["results"]) == 1
    result = status["results"][0]
    assert result["task"] == "charge_dock"
    # A KRITIKUS elvárás: sose ok=True, mert nincs valós dokkoló-integráció.
    assert result["ok"] is False
    assert "would dock here" in result.get("note", "")


def test_charge_dock_custom_fn_cannot_force_success_either():
    """Még ha egy egyedi charge_dock_fn 'ok': True-t is adna vissza (pl. egy
    jövőbeli, félig kész integráció hibásan optimista lenne), a mission.py
    a task leírása szerint SOHA nem engedheti át változatlanul — mindig
    False-ra kényszeríti, amíg nincs valós visszaigazolás bekötve."""
    rig = FakeRig(arrivals_after=1)

    def overly_optimistic_dock(waypoint):
        return {"ok": True, "note": "docked (not actually verified)"}

    runner = make_runner(rig, charge_dock_fn=overly_optimistic_dock)
    runner.submit([{"id": "dock1", "x": 5.0, "y": 5.0, "task": "charge_dock"}])
    runner.start()

    assert _wait_until(lambda: runner.status()["status"] in ("done", "aborted", "error"))
    result = runner.status()["results"][0]
    assert result["ok"] is False


def test_submit_rejects_unknown_task():
    rig = FakeRig()
    runner = make_runner(rig)
    try:
        runner.submit([{"id": "x", "x": 0, "y": 0, "task": "do_a_backflip"}])
        assert False, "should have raised ValueError"
    except ValueError as exc:
        assert "do_a_backflip" in str(exc)


def test_cannot_start_twice_while_running():
    rig = FakeRig(arrivals_after=1000)
    runner = make_runner(rig)
    runner.submit(WAYPOINTS)
    runner.start()
    assert _wait_until(lambda: runner.status()["status"] == "running")
    try:
        runner.start()
        assert False, "should have raised RuntimeError"
    except RuntimeError:
        pass
    finally:
        runner.abort()
        runner.join(timeout=5.0)


def test_start_without_submit_raises():
    rig = FakeRig()
    runner = make_runner(rig)
    try:
        runner.start()
        assert False, "should have raised RuntimeError"
    except RuntimeError:
        pass
