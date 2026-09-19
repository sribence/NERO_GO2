"""LowCmdSender is mock-only tonight: it must never have a code path that
reaches a real DDS/network call, and every command it records must have
already passed through JointSafetyManager.clamp_full() before being kept.
"""
from __future__ import annotations

import inspect
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from joint_safety import JointSafetyManager
from lowcmd_sender import LowCmdSender, _MIN_TICK_INTERVAL_S


def _stand_pose():
    return [0.0, 0.8, -1.5] * 4


def test_unsafe_target_is_clamped_before_it_reaches_the_sent_command():
    safety = JointSafetyManager()
    sender = LowCmdSender(safety)
    current_q = _stand_pose()
    unsafe_target = [9.0] * 12  # far past URDF limits and a huge single-tick jump

    command = sender.send(unsafe_target, current_q, kp=999.0, kd=999.0, tau=[999.0] * 12)

    for i, motor in enumerate(command["motor_cmd"]):
        lower, upper = safety.limits_for(i)
        assert lower <= motor["q"] <= upper, "unsafe q leaked into the sent command"
        assert motor["kp"] <= safety.max_kp
        assert motor["kd"] <= safety.max_kd
        assert abs(motor["tau"]) <= 45.43 + 1e-9  # loosest (calf) effort limit
        # request was 9.0 rad away; clamp_rate must have kept the actual
        # move to at most max_step_rad from current_q
        assert abs(motor["q"] - current_q[i]) <= safety.max_step_rad + 1e-9


def test_send_records_the_command_in_order():
    safety = JointSafetyManager()
    sender = LowCmdSender(safety)
    current_q = _stand_pose()

    assert sender.sent == []
    first = sender.send(current_q, current_q, kp=20.0, kd=1.0)
    second = sender.send(current_q, current_q, kp=20.0, kd=1.0)

    assert sender.sent == [first, second]
    assert len(sender.sent) == 2


def test_recorded_command_has_lowcmd_shape():
    safety = JointSafetyManager()
    sender = LowCmdSender(safety)
    current_q = _stand_pose()

    command = sender.send(current_q, current_q)

    assert command["head"] == (0xFE, 0xEF)
    assert command["level_flag"] == 0xFF
    assert len(command["motor_cmd"]) == 12
    for motor in command["motor_cmd"]:
        assert set(motor.keys()) == {"mode", "q", "dq", "kp", "kd", "tau"}
        assert motor["mode"] == 0x01


def test_send_with_safe_command_leaves_values_effectively_unchanged():
    safety = JointSafetyManager()
    sender = LowCmdSender(safety)
    current_q = _stand_pose()

    command = sender.send(current_q, current_q, kp=20.0, kd=1.0, tau=[0.0] * 12)

    for i, motor in enumerate(command["motor_cmd"]):
        assert math.isclose(motor["q"], current_q[i], abs_tol=1e-9)
        assert motor["kp"] == 20.0
        assert motor["kd"] == 1.0
        assert motor["tau"] == 0.0


def test_fast_repeated_send_logs_a_warning_but_does_not_raise(caplog):
    safety = JointSafetyManager()
    sender = LowCmdSender(safety, tick_interval_s=1.0)  # deliberately large for a fast test
    current_q = _stand_pose()

    sender.send(current_q, current_q)
    with caplog.at_level("WARNING"):
        sender.send(current_q, current_q)  # called well under 1.0s later

    assert any("faster than" in record.message for record in caplog.records)
    assert len(sender.sent) == 2  # the guard warns, it never blocks the send


def test_reference_tick_interval_matches_verified_500hz_sdk_loop():
    # unitree_sdk2py's own go2_stand_example.py drives its LowCmd publish
    # via RecurrentThread(interval=0.002, ...) -> 500 Hz. This module's
    # default guard must match that verified value, not an invented one.
    assert math.isclose(_MIN_TICK_INTERVAL_S, 0.002, abs_tol=1e-9)


def test_module_never_imports_unitree_sdk2py_or_dds():
    # Check actual import statements via AST, not a substring match on the
    # whole file — the docstring intentionally documents unitree_sdk2py's
    # verified field names in prose, which isn't a real import.
    import ast
    import lowcmd_sender

    source = inspect.getsource(lowcmd_sender)
    tree = ast.parse(source)
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")

    for name in imported_names:
        lowered = name.lower()
        assert not any(f in lowered for f in ("unitree_sdk2py", "dds")), (
            f"lowcmd_sender.py must not import {name!r} — "
            "no real DDS/network call is allowed to exist in this module tonight"
        )

    # And no actual attribute/call expressions invoke the real publish API.
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden_call in ("ChannelPublisher", "ChannelFactoryInitialize", "DDSChannelFactoryInitialize"):
        assert forbidden_call not in called_names


def test_build_command_has_no_crc_field_since_nothing_is_published():
    # A real LowCmd_ requires low_cmd.crc = CRC().Crc(low_cmd) computed
    # immediately before ChannelPublisher.Write(). This mock command is
    # never published, so it must not fake a CRC value either.
    safety = JointSafetyManager()
    sender = LowCmdSender(safety)
    current_q = _stand_pose()

    command = sender.build_command(current_q, current_q)
    assert "crc" not in command


def test_lowcmdsender_has_no_send_method_that_bypasses_the_safety_clamp():
    # Every public callable on LowCmdSender that could plausibly dispatch
    # a command must route through build_command()/clamp_full(). Assert by
    # construction: the only public methods are build_command and send.
    public_methods = {
        name for name, member in inspect.getmembers(LowCmdSender, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {"build_command", "send"}
