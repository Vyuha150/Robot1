"""Tests for bonbon_actuation.core.gesture_library."""

from __future__ import annotations

import pytest

from bonbon_actuation.core.gesture_library import (
    GestureDefinition,
    GestureKeyframe,
    GestureLibrary,
    ServoTarget,
    SERVO_HEAD_PAN,
    SERVO_HEAD_TILT,
    SERVO_RIGHT_SHOULDER,
    SERVO_LIMITS,
)


KNOWN_GESTURES = [
    "rest_pose", "listening_pose", "safe_folded_pose",
    "nod_yes", "shake_no", "wave", "thinking_pose",
    "greeting_pose", "apology_pose", "stop_gesture",
    "invite_gesture", "point_left", "point_right",
    "idle_scan", "emergency_attention_pose",
]


class TestGestureLibraryRegistry:
    def test_all_known_gestures_registered(self):
        for name in KNOWN_GESTURES:
            assert GestureLibrary.has(name), f"Missing gesture: {name}"

    def test_get_returns_gesture_definition(self):
        g = GestureLibrary.get("nod_yes")
        assert isinstance(g, GestureDefinition)
        assert g.name == "nod_yes"

    def test_unknown_gesture_returns_none(self):
        assert GestureLibrary.get("totally_fake_gesture_xyz") is None

    def test_has_returns_false_for_unknown(self):
        assert GestureLibrary.has("not_a_gesture") is False

    def test_list_names_contains_all_known(self):
        names = GestureLibrary.list_names()
        for g in KNOWN_GESTURES:
            assert g in names

    def test_list_names_minimum_count(self):
        assert len(GestureLibrary.list_names()) >= 13


class TestGestureDefinitionProperties:
    def test_every_gesture_has_keyframes(self):
        for name in GestureLibrary.list_names():
            g = GestureLibrary.get(name)
            assert len(g.keyframes) > 0, f"Gesture '{name}' has no keyframes"

    def test_every_gesture_has_positive_duration(self):
        for name in GestureLibrary.list_names():
            g = GestureLibrary.get(name)
            assert g.duration_sec > 0.0, f"Gesture '{name}' duration={g.duration_sec}"

    def test_duration_matches_last_keyframe(self):
        for name in GestureLibrary.list_names():
            g = GestureLibrary.get(name)
            last_kf_time = max(kf.time_offset_sec for kf in g.keyframes)
            assert abs(g.duration_sec - last_kf_time) < 1e-6, (
                f"Gesture '{name}' duration {g.duration_sec} != "
                f"last keyframe {last_kf_time}"
            )

    def test_stop_gesture_not_interruptible(self):
        assert GestureLibrary.get("stop_gesture").interruptible is False

    def test_emergency_attention_not_interruptible(self):
        assert GestureLibrary.get("emergency_attention_pose").interruptible is False

    def test_safe_folded_not_interruptible(self):
        assert GestureLibrary.get("safe_folded_pose").interruptible is False

    def test_wave_requires_clear_space(self):
        assert GestureLibrary.get("wave").requires_clear_space is True

    def test_nod_yes_is_interruptible(self):
        assert GestureLibrary.get("nod_yes").interruptible is True


class TestServoTargetsWithinLimits:
    def test_all_gesture_positions_within_servo_limits(self):
        """Every target position in every gesture must respect SERVO_LIMITS."""
        violations = []
        for name in GestureLibrary.list_names():
            g = GestureLibrary.get(name)
            for kf in g.keyframes:
                for t in kf.targets:
                    if t.servo_id not in SERVO_LIMITS:
                        violations.append(
                            f"{name}: unknown servo_id={t.servo_id}"
                        )
                        continue
                    lo, hi = SERVO_LIMITS[t.servo_id]
                    if not (lo <= t.position_deg <= hi):
                        violations.append(
                            f"{name}: servo {t.servo_id} position "
                            f"{t.position_deg}° outside [{lo}, {hi}]"
                        )
        assert violations == [], "\n".join(violations)

    def test_all_velocities_positive(self):
        for name in GestureLibrary.list_names():
            g = GestureLibrary.get(name)
            for kf in g.keyframes:
                for t in kf.targets:
                    assert t.velocity_dps > 0, (
                        f"{name}: servo {t.servo_id} has zero/negative velocity"
                    )
