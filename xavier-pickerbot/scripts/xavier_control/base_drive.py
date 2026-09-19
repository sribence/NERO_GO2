"""Mecanum-base teleop command builder for the Xavier Pickerbot Mini.

Robot: Wheeltec "Xavier Pickerbot Mini" (mecanum-wheel base + 4-DOF arm),
NOT the Unitree Go2 quadruped — do not reuse Go2 joint numbers here, this
is a completely different drivetrain (velocity Twist, not joint LowCmd).

Command shape: `geometry_msgs/Twist`-like dict with linear.x, linear.y,
angular.z. Mecanum wheels (unlike a differential-drive base) genuinely
support lateral motion, so linear.y is a real, independent control axis
here, not just left over from a generic Twist template.

Topic name (UNVERIFIED on this specific robot instance): `/cmd_vel` is the
conventional topic for Wheeltec's own `turn_on_wheeltec_robot` base driver
and is what their `wheeltec_joy_control` package publishes to. It is a
reasonable, well-documented default, but nobody has run
`rostopic info /cmd_vel` against THIS robot this session (it was
unreachable) to confirm the topic exists, its exact message type, or that
nothing else on the robot expects a different name. Treat it as "very
likely correct, not yet confirmed" — see docs/08-kezi-vezerles.md for the
live-verification procedure to run before the first real send.

SPEED CAPS BELOW ARE SAFETY-FIRST DEFAULTS, NOT MEASURED HARDWARE CEILINGS.
No load test, tape-measure timing run, or datasheet lookup has been done
for this robot's actual top speed. These numbers were chosen to be slow
enough that a first live test is very unlikely to surprise anyone, and
they should be tuned DOWN further (not up) if the robot turns out to move
faster than expected on that first test. If a real datasheet or a measured
top speed becomes available later, replace these values and update this
docstring to say so explicitly — don't just widen them.
"""

from __future__ import annotations

import time

# --- Conservative, NOT-measured-from-hardware teleop speed caps -----------
# Conservative default, not a measured hardware ceiling — tune down further
# if the robot moves faster than expected on first live test.
MAX_LINEAR_MPS = 0.15       # forward/back and strafe, metres/second
MAX_ANGULAR_RADPS = 0.3     # yaw, radians/second

# Per-tick acceleration limit: how much a single control tick is allowed to
# change linear/angular velocity, so a UI click can't jump straight to max
# speed. Mirrors the spirit of the Go2 dashboard's clamp_rate() — a manual
# teleop input should ramp, not step. Also NOT measured; picked to give a
# smooth ~0.5s ramp to max speed at a typical ~10-20 Hz UI tick rate.
MAX_LINEAR_ACCEL_MPS_PER_TICK = 0.03
MAX_ANGULAR_ACCEL_RADPS_PER_TICK = 0.06

ZERO_TWIST = {"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def build_twist(linear_x: float = 0.0, linear_y: float = 0.0, angular_z: float = 0.0) -> dict:
    """Builds a geometry_msgs/Twist-shaped dict from raw manual input,
    clamped to the conservative teleop speed caps above. Does NOT rate-limit
    against a previous command — that is TeleopRateLimiter's job, since rate
    limiting needs state across calls and this function is a pure builder.
    """
    lx = _clamp(float(linear_x), MAX_LINEAR_MPS)
    ly = _clamp(float(linear_y), MAX_LINEAR_MPS)
    az = _clamp(float(angular_z), MAX_ANGULAR_RADPS)
    return {
        "linear": {"x": lx, "y": ly, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": az},
    }


def build_stop() -> dict:
    """Explicit zero-command Twist for E-stop / disarm. Always returns a
    fresh dict (never a shared mutable reference to ZERO_TWIST) so a caller
    can't accidentally mutate the module-level constant."""
    return {"linear": {"x": 0.0, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": 0.0}}


class TeleopRateLimiter:
    """Rate-limits successive manual Twist commands so a UI click can't jump
    straight from stopped to full speed. Call `step()` once per control
    tick with the newly-requested (already speed-capped) command; it returns
    the ramped-toward command actually safe to send this tick.

    Time-aware: if step() is called less often than expected (e.g. a slow
    UI, a dropped websocket frame), the elapsed wall-clock time since the
    last call is used to scale the allowed change, so a laggy UI doesn't
    also mean a slower ramp than intended. A minimum tick is enforced so a
    near-zero elapsed time (e.g. two calls in the same frame) can't produce
    an effectively unlimited step.
    """

    _MIN_DT_S = 1.0 / 50.0  # cap the accel budget at a 50 Hz-equivalent tick, even if calls are faster

    def __init__(
        self,
        max_linear_accel: float = MAX_LINEAR_ACCEL_MPS_PER_TICK,
        max_angular_accel: float = MAX_ANGULAR_ACCEL_RADPS_PER_TICK,
        tick_hz_reference: float = 20.0,
    ):
        self.max_linear_accel = max_linear_accel
        self.max_angular_accel = max_angular_accel
        # accel budgets above are expressed "per tick" at this reference
        # rate; step() scales them by actual elapsed time so the ramp speed
        # doesn't depend on how often the caller happens to poll.
        self._tick_period_s = 1.0 / tick_hz_reference
        self.current = build_stop()
        self._last_step_monotonic = None

    def reset(self):
        """Zeros the tracked current command, e.g. on disarm/E-stop."""
        self.current = build_stop()
        self._last_step_monotonic = None

    def step(self, requested: dict) -> dict:
        """Moves self.current toward `requested` (already speed-capped, e.g.
        via build_twist()) by at most the accel-limited amount for the
        elapsed wall-clock time, and returns the new self.current."""
        now = time.monotonic()
        if self._last_step_monotonic is None:
            dt = self._tick_period_s
        else:
            dt = max(now - self._last_step_monotonic, self._MIN_DT_S)
        self._last_step_monotonic = now

        scale = dt / self._tick_period_s
        max_lin_step = self.max_linear_accel * scale
        max_ang_step = self.max_angular_accel * scale

        cur = self.current
        req = requested
        new_lx = cur["linear"]["x"] + _clamp(req["linear"]["x"] - cur["linear"]["x"], max_lin_step)
        new_ly = cur["linear"]["y"] + _clamp(req["linear"]["y"] - cur["linear"]["y"], max_lin_step)
        new_az = cur["angular"]["z"] + _clamp(req["angular"]["z"] - cur["angular"]["z"], max_ang_step)

        self.current = {
            "linear": {"x": new_lx, "y": new_ly, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": new_az},
        }
        return self.current
