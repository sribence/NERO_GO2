"""The watchdog is the last line of defence if a driving pillar dies.

It runs in a daemon thread, so an exception in it fails silently -- which
is exactly what happened on the first implementation (UnboundLocalError,
caught by this suite). These tests assert it actually stops the robot.
"""
from __future__ import annotations

import importlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))


def test_watchdog_stops_the_robot_when_commands_stop(monkeypatch):
    monkeypatch.setenv("MC_API_TOKEN", "test-token")
    monkeypatch.setenv("COMMAND_TIMEOUT_S", "0.2")
    monkeypatch.setenv("ROBOT_BACKEND", "mock")
    monkeypatch.delenv("ROBOT_CLIENT_MODE", raising=False)

    import service
    importlib.reload(service)

    service.robot.set_armed(True)
    service.move(service.MoveCmd(vx=0.5))
    assert service.robot._vx == 0.5

    # Stop commanding; the watchdog must zero the velocity on its own.
    deadline = time.time() + 3.0
    while time.time() < deadline and service.robot._vx != 0.0:
        time.sleep(0.05)
    assert service.robot._vx == 0.0, "watchdog did not stop the robot"
    assert service.state()["watchdog_trips"] >= 1


def test_estop_disarms_and_needs_no_token(monkeypatch):
    monkeypatch.setenv("MC_API_TOKEN", "test-token")
    monkeypatch.setenv("ROBOT_BACKEND", "mock")
    monkeypatch.delenv("ROBOT_CLIENT_MODE", raising=False)

    import service
    importlib.reload(service)

    service.robot.set_armed(True)
    service.move(service.MoveCmd(vx=0.4))
    result = service.estop()          # called with no credentials at all
    assert result["estop"] is True
    assert service.robot.is_armed() is False
    assert service.robot._vx == 0.0


def test_move_is_refused_when_disarmed(monkeypatch):
    monkeypatch.setenv("MC_API_TOKEN", "test-token")
    monkeypatch.setenv("ROBOT_BACKEND", "mock")
    monkeypatch.delenv("ROBOT_CLIENT_MODE", raising=False)

    import service
    importlib.reload(service)
    from fastapi import HTTPException
    import pytest

    service.robot.set_armed(False)
    with pytest.raises(HTTPException) as e:
        service.move(service.MoveCmd(vx=0.4))
    assert e.value.status_code == 409


def test_writes_fail_closed_without_a_token(monkeypatch):
    monkeypatch.delenv("MC_API_TOKEN", raising=False)
    import service
    importlib.reload(service)
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as e:
        service.require_token("anything")
    assert e.value.status_code == 503
