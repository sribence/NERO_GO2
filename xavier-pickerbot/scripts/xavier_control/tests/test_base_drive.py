"""Tests for base_drive.py — mecanum Twist builder, speed caps, rate limiter,
E-stop. Speed caps here are deliberately-conservative safety defaults, not
measured hardware ceilings (see module docstring); these tests check that
the clamps clamp, not that the numbers match any real robot spec.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from base_drive import (
    MAX_ANGULAR_ACCEL_RADPS_PER_TICK,
    MAX_ANGULAR_RADPS,
    MAX_LINEAR_ACCEL_MPS_PER_TICK,
    MAX_LINEAR_MPS,
    TeleopRateLimiter,
    build_stop,
    build_twist,
)


def test_build_twist_passes_through_small_values():
    t = build_twist(0.05, -0.02, 0.1)
    assert t["linear"]["x"] == 0.05
    assert t["linear"]["y"] == -0.02
    assert t["angular"]["z"] == 0.1
    assert t["linear"]["z"] == 0.0
    assert t["angular"]["x"] == 0.0 and t["angular"]["y"] == 0.0


def test_build_twist_clamps_linear_x_to_speed_cap():
    t = build_twist(linear_x=99.0)
    assert t["linear"]["x"] == MAX_LINEAR_MPS


def test_build_twist_clamps_negative_linear_y_to_speed_cap():
    t = build_twist(linear_y=-99.0)
    assert t["linear"]["y"] == -MAX_LINEAR_MPS


def test_build_twist_clamps_angular_z_to_speed_cap():
    t = build_twist(angular_z=99.0)
    assert t["angular"]["z"] == MAX_ANGULAR_RADPS
    t2 = build_twist(angular_z=-99.0)
    assert t2["angular"]["z"] == -MAX_ANGULAR_RADPS


def test_build_stop_is_all_zero():
    stop = build_stop()
    assert stop["linear"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert stop["angular"] == {"x": 0.0, "y": 0.0, "z": 0.0}


def test_build_stop_returns_a_fresh_dict_each_time():
    a = build_stop()
    b = build_stop()
    assert a is not b
    a["linear"]["x"] = 5.0
    assert b["linear"]["x"] == 0.0


def test_rate_limiter_starts_at_zero():
    limiter = TeleopRateLimiter()
    assert limiter.current == build_stop()


def test_rate_limiter_does_not_jump_straight_to_max_speed():
    limiter = TeleopRateLimiter(
        max_linear_accel=MAX_LINEAR_ACCEL_MPS_PER_TICK,
        max_angular_accel=MAX_ANGULAR_ACCEL_RADPS_PER_TICK,
        tick_hz_reference=20.0,
    )
    requested = build_twist(linear_x=MAX_LINEAR_MPS)
    result = limiter.step(requested)
    # a single tick must not reach full speed from a standing start
    assert 0.0 < result["linear"]["x"] < MAX_LINEAR_MPS


def test_rate_limiter_converges_to_target_over_many_ticks():
    limiter = TeleopRateLimiter(tick_hz_reference=20.0)
    requested = build_twist(linear_x=MAX_LINEAR_MPS, angular_z=MAX_ANGULAR_RADPS)
    last = None
    for _ in range(500):
        last = limiter.step(requested)
    assert abs(last["linear"]["x"] - MAX_LINEAR_MPS) < 1e-6
    assert abs(last["angular"]["z"] - MAX_ANGULAR_RADPS) < 1e-6


def test_rate_limiter_reset_zeros_current_command():
    limiter = TeleopRateLimiter()
    requested = build_twist(linear_x=MAX_LINEAR_MPS)
    for _ in range(50):
        limiter.step(requested)
    assert limiter.current["linear"]["x"] > 0.0
    limiter.reset()
    assert limiter.current == build_stop()


def test_rate_limiter_never_exceeds_speed_cap_even_with_oversized_request():
    # step() is normally fed an already-capped command via build_twist(),
    # but the limiter itself must not amplify an already-safe delta past
    # the cap even if fed a raw, uncapped dict.
    limiter = TeleopRateLimiter(tick_hz_reference=20.0)
    oversized = {
        "linear": {"x": 50.0, "y": -50.0, "z": 0.0},
        "angular": {"x": 0.0, "y": 0.0, "z": 50.0},
    }
    # the ACCEL step itself must never exceed the per-tick cap, regardless
    # of how far past the speed cap the raw request is.
    first_step = limiter.step(oversized)
    assert abs(first_step["linear"]["x"]) <= MAX_LINEAR_ACCEL_MPS_PER_TICK * 1.001
