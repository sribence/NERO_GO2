"""JointSafetyManager is the last line of defence before a manual LowCmd
command reaches the real Go2 motors. These tests assert every clamp
actually clamps, using the real URDF numbers as the reference, not the
module's own copies of them (a wrong copy in the module would still
pass a test that just re-imports the same constants).
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from joint_safety import JointSafetyManager

# Independently transcribed from static/go2_description/go2_description.urdf
# <limit lower=... upper=...> tags, so a bug in joint_safety.py's own copy
# would still be caught here.
URDF_HIP = (-1.0472, 1.0472)
URDF_CALF = (-2.7227, -0.83776)
URDF_THIGH_FRONT = (-1.5708, 3.4907)
URDF_THIGH_REAR = (-0.5236, 4.5379)
# index -> (leg, joint_type), matches FR,FL,RR,RL x hip,thigh,calf
JOINT_META = [
    (leg, jt)
    for leg in ("FR", "FL", "RR", "RL")
    for jt in ("hip", "thigh", "calf")
]


def _urdf_limit(index):
    leg, jt = JOINT_META[index]
    if jt == "hip":
        return URDF_HIP
    if jt == "calf":
        return URDF_CALF
    return URDF_THIGH_FRONT if leg in ("FR", "FL") else URDF_THIGH_REAR


def test_limits_stay_inside_urdf_hardware_range():
    safety = JointSafetyManager()
    for i in range(12):
        lower, upper = safety.limits_for(i)
        urdf_lower, urdf_upper = _urdf_limit(i)
        assert lower > urdf_lower, f"joint {i} lower bound touches hardware limit"
        assert upper < urdf_upper, f"joint {i} upper bound touches hardware limit"


def test_margin_is_five_degrees_by_default():
    safety = JointSafetyManager()
    lower, upper = safety.limits_for(0)  # FR hip
    urdf_lower, urdf_upper = URDF_HIP
    assert math.isclose(lower - urdf_lower, math.radians(5.0), abs_tol=1e-6)
    assert math.isclose(urdf_upper - upper, math.radians(5.0), abs_tol=1e-6)


def test_clamp_position_rejects_wrong_length():
    safety = JointSafetyManager()
    try:
        safety.clamp_position([0.0] * 11)
        assert False, "expected ValueError for wrong-length input"
    except ValueError:
        pass


def test_clamp_position_clips_out_of_range_command():
    safety = JointSafetyManager()
    wild = [99.0] * 12  # absurd manual-input value, e.g. a UI bug or bad joystick scale
    clamped = safety.clamp_position(wild)
    for i, value in enumerate(clamped):
        lower, upper = safety.limits_for(i)
        assert lower <= value <= upper


def test_clamp_position_leaves_safe_values_untouched():
    safety = JointSafetyManager()
    stand_pose = [0.0, 0.8, -1.5] * 4  # app.py's _STAND_HIP/_THIGH/_CALF neutral pose
    clamped = safety.clamp_position(stand_pose)
    assert clamped == stand_pose


def test_clamp_rate_limits_a_large_single_tick_jump():
    safety = JointSafetyManager(max_step_rad=math.radians(3.0))
    current = [0.0] * 12
    target = [1.0] * 12  # far larger than one tick should ever move
    limited = safety.clamp_rate(target, current)
    for value in limited:
        assert abs(value) <= math.radians(3.0) + 1e-9


def test_clamp_rate_passes_through_small_moves():
    safety = JointSafetyManager(max_step_rad=math.radians(3.0))
    current = [0.0] * 12
    target = [math.radians(1.0)] * 12
    limited = safety.clamp_rate(target, current)
    for value in limited:
        assert math.isclose(value, math.radians(1.0), abs_tol=1e-9)


def test_clamp_gains_caps_scalar_kp_kd():
    safety = JointSafetyManager(max_kp=60.0, max_kd=5.0)
    kp, kd = safety.clamp_gains(500.0, 50.0)
    assert all(v == 60.0 for v in kp)
    assert all(v == 5.0 for v in kd)


def test_clamp_gains_rejects_negative_values():
    safety = JointSafetyManager()
    kp, kd = safety.clamp_gains(-10.0, -10.0)
    assert all(v == 0.0 for v in kp)
    assert all(v == 0.0 for v in kd)


def test_clamp_torque_caps_at_urdf_effort():
    safety = JointSafetyManager()
    tau = [1000.0] * 12  # any value far past the motor's real effort rating
    clamped = safety.clamp_torque(tau)
    for value, (leg, jt) in zip(clamped, JOINT_META):
        expected = 45.43 if jt == "calf" else 23.7
        assert math.isclose(value, expected, abs_tol=1e-6)


def test_clamp_full_returns_lowcmd_ready_dict():
    safety = JointSafetyManager()
    current_q = [0.0, 0.8, -1.5] * 4
    target_q = [5.0] * 12  # deliberately unsafe: past limits AND a huge single-tick jump
    cmd = safety.clamp_full(target_q, current_q, kp=999.0, kd=999.0, tau=[999.0] * 12)
    assert set(cmd.keys()) == {"q", "kp", "kd", "tau"}
    for i, value in enumerate(cmd["q"]):
        lower, upper = safety.limits_for(i)
        assert lower <= value <= upper
    assert all(v <= safety.max_kp for v in cmd["kp"])
    assert all(v <= safety.max_kd for v in cmd["kd"])
    for value, (leg, jt) in zip(cmd["tau"], JOINT_META):
        limit = 45.43 if jt == "calf" else 23.7
        assert abs(value) <= limit + 1e-9


def test_is_safe_true_for_neutral_stand_pose():
    safety = JointSafetyManager()
    assert safety.is_safe([0.0, 0.8, -1.5] * 4)


def test_is_safe_false_for_out_of_range_value():
    safety = JointSafetyManager()
    unsafe = [0.0, 0.8, -1.5] * 4
    unsafe[1] = 10.0  # FR thigh, far past its real range
    assert not safety.is_safe(unsafe)
