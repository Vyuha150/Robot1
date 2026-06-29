"""Tests for estimate_engagement / estimate_urgency."""

from __future__ import annotations

from bonbon_human_state_fusion.core.active_speaker_tracker import RECENTLY_SPOKE, SILENT, SPEAKING
from bonbon_human_state_fusion.core.urgency_engagement_estimator import (
    estimate_engagement,
    estimate_urgency,
)


class TestEngagement:
    def test_active_interaction_is_highly_engaged(self):
        score = estimate_engagement("active_interaction", SILENT, False)
        assert score >= 0.9

    def test_left_scene_has_zero_base_engagement(self):
        score = estimate_engagement("left_scene", SILENT, False)
        assert score == 0.0

    def test_speaking_boosts_engagement(self):
        base = estimate_engagement("present", SILENT, False)
        boosted = estimate_engagement("present", SPEAKING, False)
        assert boosted > base

    def test_recent_gesture_boosts_engagement(self):
        base = estimate_engagement("present", SILENT, False)
        boosted = estimate_engagement("present", SILENT, True)
        assert boosted > base

    def test_clamped_to_one(self):
        score = estimate_engagement("active_interaction", SPEAKING, True)
        assert score <= 1.0

    def test_unknown_lifecycle_state_gets_default(self):
        score = estimate_engagement("some_future_state", SILENT, False)
        assert 0.0 <= score <= 1.0

    def test_recently_spoke_boosts_less_than_speaking(self):
        recently = estimate_engagement("present", RECENTLY_SPOKE, False)
        speaking = estimate_engagement("present", SPEAKING, False)
        assert recently < speaking


class TestUrgency:
    def test_routine_state_is_zero(self):
        assert estimate_urgency("neutral", False, False) == 0.0

    def test_safety_gesture_forces_max_urgency(self):
        assert estimate_urgency("neutral", True, False) == 1.0

    def test_emergency_text_forces_max_urgency(self):
        assert estimate_urgency("neutral", False, True) == 1.0

    def test_urgent_emotional_state_scores_high(self):
        score = estimate_urgency("urgent", False, False)
        assert score >= 0.9

    def test_strong_signal_never_diluted_by_calm_emotion(self):
        score = estimate_urgency("neutral", True, False)
        assert score == 1.0  # not averaged down by the neutral emotional reading

    def test_unknown_emotional_state_treated_as_non_urgent(self):
        assert estimate_urgency("some_future_state", False, False) == 0.0
