"""person_follow.py steering-matek + "nincs szemely -> allj meg" idozito.

Ugyanaz a stilus, mint mission-control/tests/test_watchdog.py: sima
assert-ek, monkeypatch env-valtozokra ahol kell, es itt is a "no time.sleep,
no real thread" elv — a person_lost() explicit now_ts parametert kap, igy
determinisztikusan tesztelheto valodi varakozas nelkul (ld. person_follow.py
docstringje).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from person_follow import (
    FOLLOW_CENTER_DEADBAND,
    FOLLOW_MAX_VX,
    FOLLOW_MAX_VYAW,
    FOLLOW_MIN_CONFIDENCE,
    FOLLOW_PERSON_LOST_TIMEOUT_S,
    FOLLOW_SIZE_DEADBAND,
    FOLLOW_TARGET_SIZE_FRAC,
    compute_follow_command,
    person_lost,
    pick_person_target,
)


def _bbox(x1, y1, x2, y2):
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


# --- pick_person_target ----------------------------------------------------

def test_pick_person_target_ignores_non_person_classes():
    detections = [
        {"class": "dog", "confidence": 0.99, "bbox": _bbox(0, 0, 500, 500)},
        {"class": "chair", "confidence": 0.95, "bbox": _bbox(0, 0, 500, 500)},
    ]
    assert pick_person_target(detections) is None


def test_pick_person_target_ignores_low_confidence():
    detections = [
        {"class": "person", "confidence": FOLLOW_MIN_CONFIDENCE - 0.01, "bbox": _bbox(0, 0, 100, 100)},
    ]
    assert pick_person_target(detections) is None


def test_pick_person_target_picks_largest_bbox_among_valid_persons():
    small = {"class": "person", "confidence": 0.9, "bbox": _bbox(0, 0, 50, 50)}
    large = {"class": "person", "confidence": 0.5, "bbox": _bbox(0, 0, 300, 300)}
    detections = [small, large]
    assert pick_person_target(detections) is large


def test_pick_person_target_empty_or_none_detections():
    assert pick_person_target([]) is None
    assert pick_person_target(None) is None


# --- compute_follow_command --------------------------------------------------

def test_person_centered_and_at_target_distance_gives_zero_command():
    frame_w, frame_h = 640, 480
    target_h = FOLLOW_TARGET_SIZE_FRAC * frame_h
    bbox = _bbox(frame_w / 2 - 20, 0, frame_w / 2 + 20, target_h)
    vx, vyaw = compute_follow_command(bbox, frame_w, frame_h)
    assert vx == 0.0
    assert vyaw == 0.0


def test_person_left_of_center_turns_left_positive_vyaw():
    # Bbox entirely in the left half -> the robot must turn TOWARD it.
    frame_w, frame_h = 640, 480
    bbox = _bbox(0, 0, 100, 100)
    vx, vyaw = compute_follow_command(bbox, frame_w, frame_h)
    assert vyaw > 0.0


def test_person_right_of_center_turns_right_negative_vyaw():
    frame_w, frame_h = 640, 480
    bbox = _bbox(frame_w - 100, 0, frame_w, 100)
    vx, vyaw = compute_follow_command(bbox, frame_w, frame_h)
    assert vyaw < 0.0


def test_small_offset_inside_deadband_is_zero():
    frame_w, frame_h = 640, 480
    half_deadband_px = frame_w * (FOLLOW_CENTER_DEADBAND / 2.0)
    cx = frame_w / 2 + half_deadband_px
    bbox = _bbox(cx - 5, 0, cx + 5, 10)
    _, vyaw = compute_follow_command(bbox, frame_w, frame_h)
    assert vyaw == 0.0


def test_small_far_person_drives_forward():
    frame_w, frame_h = 640, 480
    # A tiny bbox height -> far below the target size fraction -> forward.
    bbox = _bbox(frame_w / 2 - 10, 0, frame_w / 2 + 10, 10)
    vx, _ = compute_follow_command(bbox, frame_w, frame_h)
    assert vx > 0.0


def test_close_person_never_drives_backward():
    frame_w, frame_h = 640, 480
    # bbox fills almost the whole frame height -> "too close", but the
    # follow behaviour is conservative and must not reverse automatically.
    bbox = _bbox(frame_w / 2 - 10, 0, frame_w / 2 + 10, frame_h)
    vx, _ = compute_follow_command(bbox, frame_w, frame_h)
    assert vx == 0.0


def test_vx_never_exceeds_max_even_for_extreme_input():
    frame_w, frame_h = 640, 480
    bbox = _bbox(frame_w / 2 - 1, 0, frame_w / 2 + 1, 1)  # essentially a point, far away
    vx, _ = compute_follow_command(bbox, frame_w, frame_h)
    assert 0.0 <= vx <= FOLLOW_MAX_VX


def test_vyaw_never_exceeds_max_even_for_extreme_offset():
    frame_w, frame_h = 640, 480
    bbox = _bbox(-10000, 0, -9999, 10)  # way off-frame to the left
    _, vyaw = compute_follow_command(bbox, frame_w, frame_h)
    assert -FOLLOW_MAX_VYAW <= vyaw <= FOLLOW_MAX_VYAW


def test_zero_frame_size_is_handled_without_division_error():
    bbox = _bbox(0, 0, 10, 10)
    assert compute_follow_command(bbox, 0, 480) == (0.0, 0.0)
    assert compute_follow_command(bbox, 640, 0) == (0.0, 0.0)


# --- person_lost timeout ----------------------------------------------------

def test_person_lost_is_true_when_never_seen():
    assert person_lost(None, now_ts=100.0) is True


def test_person_lost_is_false_within_timeout():
    assert person_lost(last_seen_ts=10.0, now_ts=10.0 + FOLLOW_PERSON_LOST_TIMEOUT_S - 0.1) is False


def test_person_lost_is_true_after_timeout():
    assert person_lost(last_seen_ts=10.0, now_ts=10.0 + FOLLOW_PERSON_LOST_TIMEOUT_S + 0.1) is True


def test_person_lost_respects_custom_timeout():
    assert person_lost(last_seen_ts=0.0, now_ts=1.0, timeout_s=5.0) is False
    assert person_lost(last_seen_ts=0.0, now_ts=6.1, timeout_s=5.0) is True


def test_person_lost_exact_boundary_is_not_yet_lost():
    # Strictly greater-than in the implementation -> exactly at the
    # timeout boundary the person is NOT considered lost yet.
    assert person_lost(last_seen_ts=0.0, now_ts=FOLLOW_PERSON_LOST_TIMEOUT_S, timeout_s=FOLLOW_PERSON_LOST_TIMEOUT_S) is False
