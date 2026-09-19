"""MOCK-ONLY arm/gripper command builder for the Xavier Pickerbot Mini's
4-DOF arm (Wheeltec `mini_mec_four_arm` + `mini_mec_four_arm_moveit_config`).

Status (2026-09-18, updated after a live session on the real robot): this
module NEVER talks to a real robot. It never imports rospy, actionlib,
moveit_commander, or any ROS client library, and it never constructs or
publishes to a real topic/action name. Everything `send()` produces is only
appended to `self.sent` for tests/UI to inspect. There is no env-var, flag,
or code path anywhere in this file that enables a real send — mirroring the
Go2 dashboard's lowcmd_sender.py house pattern, the real publish path is
simply NOT IMPLEMENTED here, not merely disabled, so nothing can be flipped
on by mistake.

LIVE-VERIFIED (2026-09-18, robot reachable, bringup started for read-only
inspection, base on the floor, no arm command ever sent):
- Real topic: `/arm_cmd`, type `std_msgs/Float32MultiArray`, subscribed by
  the `/wheeltec_robot` node (same node as `/cmd_vel`, not a separate MoveIt
  action server). Confirmed via `rostopic info /arm_cmd` and by reading
  `wheeltec_robot.cpp`'s `joint_states_Callback` on the robot.
- `data` is exactly 4 floats: `[j1_rad, j2_rad, j3_rad, gripper_raw]`.
  j1/j2/j3 are sent as radians, then internally scaled ×1000 and packed
  into int16 by the firmware bridge — callers of this module should still
  just pass radians, the scaling is the robot's own serial-protocol detail.
  `gripper_raw` is cast straight to `uint8_t` with NO scaling in the C++
  source — its real 0..255 (or narrower) open/close convention was NOT
  found anywhere else in the source tree (no other in-repo publisher of
  `/arm_cmd` to learn the convention from), so it is still UNVERIFIED.
- Real joint names/limits, read from `mini_mec_moveit_four.urdf` on the
  robot (`turn_on_wheeltec_robot/urdf/mini_mec_moveit_four.urdf`): only
  `j1_joint`, `j2_joint`, `j3_joint` are independently commandable via
  `/arm_cmd`; each is `type="revolute"`, limit `lower="-0.785" upper="0.785"`
  (±45°), `effort="100"` (unit unclear — likely a generic MoveIt-exporter
  placeholder, not a measured torque spec), `velocity="0"` (unspecified by
  the URDF, NOT "unlimited" — do not assume any particular safe speed from
  this). The `j4_1_joint`..`j4_6_joint` names seen in `/joint_states` are a
  mechanically-linked gripper finger assembly, not independently
  commandable — the single `gripper_raw` value in `/arm_cmd` drives all of
  them together.

STILL UNVERIFIED / left mock-only on purpose:
- The exact `gripper_raw` value range and what "open" vs "closed" means
  numerically (0..255? 0..1? a specific pair of values?).
- Real accel/velocity behavior in practice — the URDF `velocity="0"` field
  gives no usable ceiling, so no rate-limit number here is backed by a
  measurement (unlike `base_drive.py`, which errs toward a conservative
  guessed teleop cap; the arm has a collision risk with the gripper/base/
  whatever it's holding, so a real send path is not being added until an
  operator does a deliberate, supervised first physical joint-by-joint
  test with the gripper convention confirmed by direct observation).
- No physical arm motion command has ever been sent to this robot this
  session or before, as far as this codebase's history shows.

Given the above, this module keeps j1/j2/j3 limits as REAL (not
placeholder) — `JOINT_LIMITS_RAD` below is the actual URDF data — but
stays mock-only end to end until a deliberate follow-up task builds a real
sender AND someone has watched the arm move on the first few commands with
a hand near the power switch.

4-DOF ARM NOTE: with only 3 independently-commandable arm joints + 1
gripper DOF, this arm cannot reach an arbitrary 6D (position + orientation)
pose — that needs at least 6 DOF. Only a position-based target makes
sense here; full pose IK is not offered by this module.
"""

from __future__ import annotations

import time

# REAL, live-verified 2026-09-18 from mini_mec_moveit_four.urdf on the
# actual robot (j1_joint, j2_joint, j3_joint — see module docstring). Order
# matches the /arm_cmd Float32MultiArray data[0..2] order confirmed in
# wheeltec_robot.cpp's joint_states_Callback.
JOINT_LIMITS_RAD = [
    (-0.785, 0.785),   # j1_joint — URDF <limit lower upper>, verified
    (-0.785, 0.785),   # j2_joint — URDF <limit lower upper>, verified
    (-0.785, 0.785),   # j3_joint — URDF <limit lower upper>, verified
]
NUM_JOINTS = len(JOINT_LIMITS_RAD)

# Gripper (arm_cmd data[3], cast to uint8_t by the firmware bridge) — the
# real open/closed numeric convention is UNVERIFIED (see docstring), so
# this stays a conservative placeholder 0..1 fraction for the mock UI only.
GRIPPER_CLOSED = 0.0
GRIPPER_OPEN = 1.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


class ArmSafety:
    """Clamps a requested joint-angle list to PLACEHOLDER_JOINT_LIMITS_RAD.
    Kept as its own small class (mirroring Go2's JointSafetyManager split
    from LowCmdSender) so the clamp logic can be unit-tested and reused
    independently of the mock sender."""

    def __init__(self, limits=JOINT_LIMITS_RAD):
        self.limits = list(limits)

    def clamp_joints(self, q):
        if len(q) != len(self.limits):
            raise ValueError(f"expected {len(self.limits)} joint values, got {len(q)}")
        return [_clamp(float(v), lower, upper) for v, (lower, upper) in zip(q, self.limits)]

    def clamp_gripper(self, value: float) -> float:
        return _clamp(float(value), GRIPPER_CLOSED, GRIPPER_OPEN)

    def is_safe(self, q) -> bool:
        if len(q) != len(self.limits):
            return False
        return all(lower <= v <= upper for v, (lower, upper) in zip(q, self.limits))


class MockArmSender:
    """Records mock arm/gripper commands. NEVER sends anything to a real
    robot — see module docstring. Every public method just clamps via
    ArmSafety and appends a plain dict to self.sent; there is no other
    public entry point that could bypass the clamp.
    """

    def __init__(self, safety: ArmSafety | None = None):
        self.safety = safety or ArmSafety()
        self.sent = []  # list of {"kind": "joints"|"gripper", ...}, oldest first

    def send_joint_targets(self, q):
        """MOCK send of a joint-angle target. Clamps via ArmSafety, records
        the command, and returns it. No topic is published; no ROS API is
        called."""
        safe_q = self.safety.clamp_joints(q)
        command = {
            "kind": "joints",
            "q": safe_q,
            "note": "MOCK ONLY — not sent to any real topic/robot",
            "recorded_at_monotonic": time.monotonic(),
        }
        self.sent.append(command)
        return command

    def send_gripper(self, value: float):
        """MOCK send of a gripper open/close command (0.0 closed .. 1.0
        open). Clamps via ArmSafety, records the command, and returns it."""
        safe_value = self.safety.clamp_gripper(value)
        command = {
            "kind": "gripper",
            "value": safe_value,
            "note": "MOCK ONLY — not sent to any real topic/robot",
            "recorded_at_monotonic": time.monotonic(),
        }
        self.sent.append(command)
        return command

    def open_gripper(self):
        """Convenience wrapper for send_gripper(GRIPPER_OPEN)."""
        return self.send_gripper(GRIPPER_OPEN)

    def close_gripper(self):
        """Convenience wrapper for send_gripper(GRIPPER_CLOSED)."""
        return self.send_gripper(GRIPPER_CLOSED)
