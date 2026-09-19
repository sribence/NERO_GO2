"""Joint-level safety clamp for manual LowCmd control of Go2 legs.

Position limits taken from static/go2_description/go2_description.urdf
(revolute joint <limit> tags). Effort limits from the same URDF entries
(hip/thigh 23.7 Nm, calf 45.43 Nm). Velocity limit from URDF too
(hip/thigh 30.1 rad/s, calf 15.70 rad/s) — clamped further here by a
much stricter per-step rate limit, since URDF velocity is a motor
spec ceiling, not a safe manual-teleop speed.

Joint order convention matches app.py's MOTOR_NAMES: FR, FL, RR, RL,
each hip/thigh/calf (12 values total).
"""

import math

# (lower, upper) in radians, straight from the URDF, per joint type.
# Front legs (FR, FL) and rear legs (RR, RL) have different thigh limits.
_HIP_LIMIT = (-1.0472, 1.0472)
_CALF_LIMIT = (-2.7227, -0.83776)
_THIGH_LIMIT_FRONT = (-1.5708, 3.4907)
_THIGH_LIMIT_REAR = (-0.5236, 4.5379)

# Effort (Nm) limits, straight from URDF <limit effort=...>.
_HIP_EFFORT = 23.7
_THIGH_EFFORT = 23.7
_CALF_EFFORT = 45.43

_LEG_ORDER = ["FR", "FL", "RR", "RL"]
_FRONT_LEGS = ("FR", "FL")

_SAFETY_MARGIN_RAD = math.radians(5.0)  # keep 5 degrees clear of hardware limit

# Manual-teleop per-step rate limit — well below URDF velocity spec
# (hip/thigh 30.1 rad/s, calf 15.70 rad/s), which is a motor ceiling,
# not a safe speed for a human-driven joystick command.
_MAX_STEP_RAD = math.radians(3.0)  # max |Δq| allowed per control tick

# kp (stiffness) / kd (damping) caps for manual mode. Too-high kp on a
# LowCmd joint snaps it toward the target hard enough to shock the gearbox;
# too-low kd lets it oscillate. These are conservative teleop defaults,
# not the firmware's own trot-gait gains.
_MAX_KP = 60.0
_MAX_KD = 5.0

_EFFORT_LIMITS = {"hip": _HIP_EFFORT, "thigh": _THIGH_EFFORT, "calf": _CALF_EFFORT}
_JOINT_TYPES = ["hip", "thigh", "calf"] * 4


class JointSafetyManager:
    """Full safety gate for a manual LowCmd command: position clamp,
    per-step rate limit, and kp/kd/tau clamp. Call clamp_full() once per
    control tick before sending anything to the robot.

    Usage:
        safety = JointSafetyManager()
        safe_cmd = safety.clamp_full(requested_q, current_q, kp, kd, tau)
    """

    def __init__(self, margin_rad=_SAFETY_MARGIN_RAD, max_step_rad=_MAX_STEP_RAD,
                 max_kp=_MAX_KP, max_kd=_MAX_KD):
        self.margin_rad = margin_rad
        self.max_step_rad = max_step_rad
        self.max_kp = max_kp
        self.max_kd = max_kd
        self._limits = self._build_limits(margin_rad)

    @staticmethod
    def _build_limits(margin_rad):
        limits = []
        for leg in _LEG_ORDER:
            thigh_limit = _THIGH_LIMIT_FRONT if leg in _FRONT_LEGS else _THIGH_LIMIT_REAR
            for lower, upper in (_HIP_LIMIT, thigh_limit, _CALF_LIMIT):
                limits.append((lower + margin_rad, upper - margin_rad))
        return limits

    def limits_for(self, joint_index):
        """Returns (lower, upper) safe position bound in radians for joint_index (0-11)."""
        return self._limits[joint_index]

    def clamp_position(self, q):
        """Clamps a 12-value joint command list/tuple to safe position bounds.
        Returns a new list; input is not mutated. Raises ValueError if
        q does not have exactly 12 values."""
        if len(q) != 12:
            raise ValueError(f"expected 12 joint values, got {len(q)}")
        return [min(max(value, lower), upper) for value, (lower, upper) in zip(q, self._limits)]

    def clamp_rate(self, target_q, current_q):
        """Limits |target_q[i] - current_q[i]| to max_step_rad, so one
        control tick can't jump the joint far in a single command
        regardless of what the caller asked for."""
        if len(target_q) != 12 or len(current_q) != 12:
            raise ValueError("expected 12 joint values for both target_q and current_q")
        out = []
        for target, current in zip(target_q, current_q):
            delta = max(-self.max_step_rad, min(self.max_step_rad, target - current))
            out.append(current + delta)
        return out

    def clamp_gains(self, kp, kd):
        """Clamps per-joint stiffness (kp) and damping (kd) lists to safe
        teleop ceilings. Scalars are broadcast to all 12 joints."""
        kp_list = [kp] * 12 if isinstance(kp, (int, float)) else list(kp)
        kd_list = [kd] * 12 if isinstance(kd, (int, float)) else list(kd)
        if len(kp_list) != 12 or len(kd_list) != 12:
            raise ValueError("expected 12 joint values for both kp and kd")
        kp_clamped = [min(max(v, 0.0), self.max_kp) for v in kp_list]
        kd_clamped = [min(max(v, 0.0), self.max_kd) for v in kd_list]
        return kp_clamped, kd_clamped

    def clamp_torque(self, tau):
        """Clamps a 12-value feedforward torque command to each joint's
        URDF effort limit (hip/thigh 23.7 Nm, calf 45.43 Nm)."""
        if len(tau) != 12:
            raise ValueError("expected 12 joint values for tau")
        out = []
        for value, joint_type in zip(tau, _JOINT_TYPES):
            limit = _EFFORT_LIMITS[joint_type]
            out.append(min(max(value, -limit), limit))
        return out

    def clamp_full(self, target_q, current_q, kp=20.0, kd=1.0, tau=None):
        """One-call safety gate for a manual LowCmd command:
        1. rate-limit the requested target against the current position
        2. clamp the rate-limited result to safe position bounds
        3. clamp kp/kd to teleop ceilings
        4. clamp tau (defaults to zero feedforward) to effort limits
        Returns a dict ready to fill into a LowCmd message:
        {"q": [...], "kp": [...], "kd": [...], "tau": [...]}."""
        rate_limited = self.clamp_rate(target_q, current_q)
        safe_q = self.clamp_position(rate_limited)
        safe_kp, safe_kd = self.clamp_gains(kp, kd)
        safe_tau = self.clamp_torque(tau if tau is not None else [0.0] * 12)
        return {"q": safe_q, "kp": safe_kp, "kd": safe_kd, "tau": safe_tau}

    def is_safe(self, q):
        """True if every value in q (12 floats) is already inside safe position bounds."""
        if len(q) != 12:
            return False
        return all(lower <= value <= upper for value, (lower, upper) in zip(q, self._limits))
