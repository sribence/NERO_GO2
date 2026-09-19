"""Tests for arm_control.py — MOCK-ONLY arm/gripper module. These tests
must prove two separate things: (1) the placeholder joint-limit clamp
actually clamps, and (2) the module structurally cannot reach a real ROS
topic/action — no rospy/actionlib/moveit_commander import exists, mirroring
the Go2 dashboard's test_lowcmd_sender.py AST-based guarantee.
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arm_control import (
    GRIPPER_CLOSED,
    GRIPPER_OPEN,
    NUM_JOINTS,
    JOINT_LIMITS_RAD,
    ArmSafety,
    MockArmSender,
)


def _mid_pose():
    return [0.0] * NUM_JOINTS


def test_clamp_joints_rejects_wrong_length():
    safety = ArmSafety()
    try:
        safety.clamp_joints([0.0] * (NUM_JOINTS - 1))
        assert False, "expected ValueError for wrong-length input"
    except ValueError:
        pass


def test_clamp_joints_clips_out_of_range_command():
    safety = ArmSafety()
    wild = [99.0] * NUM_JOINTS
    clamped = safety.clamp_joints(wild)
    for value, (lower, upper) in zip(clamped, JOINT_LIMITS_RAD):
        assert lower <= value <= upper


def test_clamp_joints_clips_large_negative_command():
    safety = ArmSafety()
    wild = [-99.0] * NUM_JOINTS
    clamped = safety.clamp_joints(wild)
    for value, (lower, upper) in zip(clamped, JOINT_LIMITS_RAD):
        assert lower <= value <= upper


def test_clamp_joints_leaves_safe_values_untouched():
    safety = ArmSafety()
    safe = _mid_pose()
    assert safety.clamp_joints(safe) == safe


def test_clamp_gripper_caps_to_open_closed_range():
    safety = ArmSafety()
    assert safety.clamp_gripper(5.0) == GRIPPER_OPEN
    assert safety.clamp_gripper(-5.0) == GRIPPER_CLOSED
    assert safety.clamp_gripper(0.5) == 0.5


def test_is_safe_true_for_zero_pose():
    safety = ArmSafety()
    assert safety.is_safe(_mid_pose())


def test_is_safe_false_for_out_of_range_pose():
    safety = ArmSafety()
    bad = _mid_pose()
    bad[0] = 99.0
    assert not safety.is_safe(bad)


def test_mock_sender_records_clamped_joint_command():
    sender = MockArmSender()
    command = sender.send_joint_targets([99.0] * NUM_JOINTS)
    for value, (lower, upper) in zip(command["q"], JOINT_LIMITS_RAD):
        assert lower <= value <= upper
    assert sender.sent == [command]
    assert "MOCK" in command["note"]


def test_mock_sender_records_gripper_open_close():
    sender = MockArmSender()
    opened = sender.open_gripper()
    closed = sender.close_gripper()
    assert opened["value"] == GRIPPER_OPEN
    assert closed["value"] == GRIPPER_CLOSED
    assert sender.sent == [opened, closed]


def test_mock_sender_gripper_value_is_clamped():
    sender = MockArmSender()
    command = sender.send_gripper(50.0)
    assert command["value"] == GRIPPER_OPEN


def test_mock_sender_has_no_public_method_beyond_the_known_safe_set():
    # Guards against someone quietly adding a "real send" method later
    # without updating this test/the docs.
    public_methods = {
        name for name, member in inspect.getmembers(MockArmSender, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {
        "send_joint_targets",
        "send_gripper",
        "open_gripper",
        "close_gripper",
    }


def test_module_never_imports_real_ros_client_libraries():
    import ast
    import arm_control

    source = inspect.getsource(arm_control)
    tree = ast.parse(source)
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")

    forbidden_fragments = ("rospy", "actionlib", "moveit_commander", "roslibpy", "roslib")
    for name in imported_names:
        lowered = name.lower()
        assert not any(f in lowered for f in forbidden_fragments), (
            f"arm_control.py must not import {name!r} — this module stays "
            "mock-only until real joint limits/topic names are verified"
        )


def test_module_never_calls_a_real_publish_api():
    import ast
    import arm_control

    source = inspect.getsource(arm_control)
    tree = ast.parse(source)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden_calls = ("Publisher", "ServiceProxy", "SimpleActionClient", "init_node")
    for forbidden in forbidden_calls:
        assert forbidden not in called_names


def test_module_never_references_a_real_topic_or_action_name_string():
    # No hardcoded '/something' path-like string literal anywhere in the
    # source — this module should never even mention a real topic name,
    # since none has been verified for the arm.
    import ast
    import arm_control

    source = inspect.getsource(arm_control)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.startswith("/"), (
                f"arm_control.py contains a topic/action-like string literal "
                f"{node.value!r} — this module must not reference any real "
                "ROS topic/action name"
            )
