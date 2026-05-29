"""Tests for bonbon_actuation.core.motion_profile."""

from __future__ import annotations

import pytest

from bonbon_actuation.core.gesture_library import GestureLibrary
from bonbon_actuation.core.motion_profile import MotionProfileGenerator, MotionStep


class TestStepGeneration:
    def setup_method(self):
        self.gen = MotionProfileGenerator()

    def test_step_count_matches_keyframe_count(self):
        gesture = GestureLibrary.get("nod_yes")
        steps = self.gen.generate_steps(gesture, 1.0)
        assert len(steps) == len(gesture.keyframes)

    def test_first_step_progress_near_zero(self):
        gesture = GestureLibrary.get("wave")
        steps = self.gen.generate_steps(gesture, 1.0)
        assert steps[0].progress == pytest.approx(0.0, abs=0.3)

    def test_last_step_progress_is_one(self):
        gesture = GestureLibrary.get("nod_yes")
        steps = self.gen.generate_steps(gesture, 1.0)
        assert steps[-1].progress == pytest.approx(1.0, abs=1e-6)

    def test_steps_are_in_ascending_time_order(self):
        gesture = GestureLibrary.get("wave")
        steps = self.gen.generate_steps(gesture, 1.0)
        times = [s.elapsed_sec for s in steps]
        assert times == sorted(times)

    def test_empty_gesture_returns_empty_list(self):
        from bonbon_actuation.core.gesture_library import GestureDefinition
        empty_gesture = GestureDefinition(
            name="empty", description="no keyframes",
            keyframes=[], duration_sec=1.0,
        )
        steps = self.gen.generate_steps(empty_gesture, 1.0)
        assert steps == []


class TestSpeedScaling:
    def setup_method(self):
        self.gen = MotionProfileGenerator()

    def test_double_speed_halves_timestamps(self):
        gesture = GestureLibrary.get("nod_yes")
        steps_1x = self.gen.generate_steps(gesture, speed_scale=1.0)
        steps_2x = self.gen.generate_steps(gesture, speed_scale=2.0)
        assert len(steps_1x) == len(steps_2x)
        for s1, s2 in zip(steps_1x, steps_2x):
            assert s2.elapsed_sec == pytest.approx(s1.elapsed_sec / 2.0, rel=0.01)

    def test_double_speed_doubles_velocities(self):
        gesture = GestureLibrary.get("nod_yes")
        steps_1x = self.gen.generate_steps(gesture, speed_scale=1.0)
        steps_2x = self.gen.generate_steps(gesture, speed_scale=2.0)
        for s1, s2 in zip(steps_1x, steps_2x):
            for t1, t2 in zip(s1.targets, s2.targets):
                assert t2.velocity_dps == pytest.approx(t1.velocity_dps * 2.0, rel=0.01)

    def test_speed_scale_below_min_clamped_to_0_1(self):
        gesture = GestureLibrary.get("nod_yes")
        steps_min = self.gen.generate_steps(gesture, speed_scale=0.001)
        steps_clamped = self.gen.generate_steps(gesture, speed_scale=0.1)
        # Both should produce the same result after clamping
        for s1, s2 in zip(steps_min, steps_clamped):
            assert abs(s1.elapsed_sec - s2.elapsed_sec) < 1e-6

    def test_speed_scale_above_max_clamped_to_2(self):
        gesture = GestureLibrary.get("nod_yes")
        steps_max = self.gen.generate_steps(gesture, speed_scale=100.0)
        steps_clamped = self.gen.generate_steps(gesture, speed_scale=2.0)
        for s1, s2 in zip(steps_max, steps_clamped):
            assert abs(s1.elapsed_sec - s2.elapsed_sec) < 1e-6

    def test_positions_unchanged_by_speed_scale(self):
        gesture = GestureLibrary.get("wave")
        steps_1x = self.gen.generate_steps(gesture, speed_scale=1.0)
        steps_2x = self.gen.generate_steps(gesture, speed_scale=2.0)
        for s1, s2 in zip(steps_1x, steps_2x):
            for t1, t2 in zip(s1.targets, s2.targets):
                assert t1.position_deg == t2.position_deg


class TestMotionStepStructure:
    def setup_method(self):
        self.gen = MotionProfileGenerator()

    def test_step_has_targets(self):
        gesture = GestureLibrary.get("greeting_pose")
        steps = self.gen.generate_steps(gesture, 1.0)
        for step in steps:
            assert isinstance(step.targets, list)
            # Each step that had targets in the keyframe should have targets
            # (steps from keyframes without targets will have empty lists)

    def test_progress_monotonically_increasing(self):
        gesture = GestureLibrary.get("wave")
        steps = self.gen.generate_steps(gesture, 1.0)
        if len(steps) > 1:
            for i in range(1, len(steps)):
                assert steps[i].progress >= steps[i-1].progress

    def test_progress_never_exceeds_one(self):
        for name in GestureLibrary.list_names():
            gesture = GestureLibrary.get(name)
            steps = self.gen.generate_steps(gesture, 1.0)
            for step in steps:
                assert step.progress <= 1.0 + 1e-9
