"""Unit tests for GestureTemporalSmoother — majority-vote smoothing, cooldown,
and the temporal_stability fraction (added for GestureEvent.temporal_stability).
"""

from __future__ import annotations

from bonbon_gesture.config.gesture_config import GestureConfig
from bonbon_gesture.logic.temporal_smoother import GestureTemporalSmoother


class TestMajorityVote:
    def test_no_event_below_min_votes(self):
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=1.0)
        s = GestureTemporalSmoother(cfg)
        assert s.update(1, "wave", 0.9) is None  # only 1 vote so far

    def test_fires_once_majority_reached(self):
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=1.0)
        s = GestureTemporalSmoother(cfg)
        s.update(1, "wave", 0.9)
        result = s.update(1, "wave", 0.9)
        assert result is not None
        assert result[0] == "wave"

    def test_none_gesture_never_fires(self):
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=1.0)
        s = GestureTemporalSmoother(cfg)
        for _ in range(5):
            assert s.update(1, "none", 0.0) is None


class TestTemporalStability:
    def test_stability_is_one_when_window_fully_agrees(self):
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=1.0)
        s = GestureTemporalSmoother(cfg)
        s.update(1, "wave", 0.9)
        result = s.update(1, "wave", 0.9)
        stability = result[5]
        assert abs(stability - 1.0) < 1e-6

    def test_stability_reflects_partial_agreement(self):
        cfg = GestureConfig(temporal_window=4, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        s.update(1, "wave", 0.9)
        s.update(1, "wave", 0.9)
        s.update(1, "stop_palm", 0.9)  # one dissenting frame in the window
        result = s.update(1, "wave", 0.9)
        assert result is not None
        assert 0.0 < result[5] < 1.0

    def test_stability_in_valid_range(self):
        cfg = GestureConfig(temporal_window=5, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        results = [s.update(2, "thumbs_up", 0.8) for _ in range(6)]
        for r in results:
            if r is not None:
                assert 0.0 <= r[5] <= 1.0


class TestCooldown:
    def test_non_safety_gesture_respects_cooldown(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=100.0)
        s = GestureTemporalSmoother(cfg)
        results = [s.update(3, "pointing", 0.9) for _ in range(6)]
        fired = [r for r in results if r is not None]
        assert len(fired) == 1

    def test_safety_gesture_bypasses_cooldown(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=100.0)
        s = GestureTemporalSmoother(cfg)
        results = [s.update(4, "stop_palm", 0.9) for _ in range(6)]
        fired = [r for r in results if r is not None]
        assert len(fired) >= 2


class TestHeldAndStartedFlags:
    def test_just_started_true_on_first_fire(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=1.0)
        s = GestureTemporalSmoother(cfg)
        s.update(5, "wave", 0.9)
        result = s.update(5, "wave", 0.9)
        assert result[2] is True  # just_started

    def test_is_held_true_on_subsequent_fire(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        s.update(6, "stop_palm", 0.9)
        s.update(6, "stop_palm", 0.9)
        result = s.update(6, "stop_palm", 0.9)
        assert result[3] is True  # is_held


class TestNotifyPersonLost:
    def test_returns_just_ended_event_for_held_gesture(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        s.update(9, "wave", 0.9)
        s.update(9, "wave", 0.9)
        result = s.notify_person_lost(9)
        assert result is not None
        assert result[0] == "wave"
        assert result[4] is True  # just_ended
        assert result[5] == 1.0  # stability reported as fully confirmed

    def test_returns_none_when_no_gesture_was_held(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        assert s.notify_person_lost(999) is None

    def test_clears_window_state_for_that_tracking_id(self):
        cfg = GestureConfig(temporal_window=3, gesture_cooldown_sec=0.0)
        s = GestureTemporalSmoother(cfg)
        s.update(10, "wave", 0.9)
        s.notify_person_lost(10)
        assert 10 not in s._windows
        assert 10 not in s._prev_gesture
