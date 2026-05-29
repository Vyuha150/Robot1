"""Tests for bonbon_behavior_engine.core.emotion_response_planner."""

from __future__ import annotations

import pytest

from bonbon_behavior_engine.core.emotion_response_planner import (
    EmotionAwareResponsePlanner,
    ResponsePlan,
)


class TestBasicEmotionPlanning:
    def setup_method(self):
        self.planner = EmotionAwareResponsePlanner()

    def test_happy_response_is_warm(self):
        plan = self.planner.plan("happy")
        assert plan.tts_emotion == "warm"
        assert plan.gesture_name == "wave"

    def test_sad_response_is_warm_and_slow(self):
        plan = self.planner.plan("sad")
        assert plan.tts_emotion == "warm"
        assert plan.tts_speed_scale < 1.0

    def test_angry_response_is_calm(self):
        plan = self.planner.plan("angry")
        assert plan.tts_emotion == "calm"
        assert plan.tts_speed_scale <= 0.9

    def test_fearful_response_is_calm_and_slow(self):
        plan = self.planner.plan("fearful")
        assert plan.tts_emotion == "calm"
        assert plan.tts_speed_scale <= 0.85

    def test_distressed_has_acknowledgment(self):
        plan = self.planner.plan("distressed", emotion_confidence=0.8)
        assert len(plan.acknowledgment_text) > 0

    def test_neutral_has_listening_pose(self):
        plan = self.planner.plan("neutral")
        assert plan.gesture_name == "listening_pose"

    def test_returns_response_plan_object(self):
        plan = self.planner.plan("happy")
        assert isinstance(plan, ResponsePlan)

    def test_unknown_emotion_returns_default(self):
        plan = self.planner.plan("bored_and_tired")
        assert isinstance(plan, ResponsePlan)
        assert plan.gesture_name  # has a gesture


class TestEmergencyOverride:
    def setup_method(self):
        self.planner = EmotionAwareResponsePlanner()

    def test_is_emergency_overrides_all(self):
        plan = self.planner.plan("happy", is_emergency=True)
        assert plan.gesture_name == "emergency_attention_pose"
        assert plan.urgency == 1.0

    def test_emergency_keyword_overrides_all(self):
        plan = self.planner.plan("neutral", has_emergency_keyword=True)
        assert plan.urgency == 1.0

    def test_emergency_has_alert_text(self):
        plan = self.planner.plan("neutral", is_emergency=True)
        assert "staff" in plan.acknowledgment_text.lower() or \
               "emergency" in plan.acknowledgment_text.lower()


class TestLowConfidence:
    def setup_method(self):
        self.planner = EmotionAwareResponsePlanner()

    def test_low_confidence_falls_back_to_neutral(self):
        # Sad with only 20% confidence → neutral plan
        plan_high = self.planner.plan("sad", emotion_confidence=0.9)
        plan_low  = self.planner.plan("sad", emotion_confidence=0.2)
        # Low confidence plan should be less urgent
        assert plan_low.urgency <= plan_high.urgency

    def test_high_confidence_uses_specific_plan(self):
        plan = self.planner.plan("angry", emotion_confidence=0.9)
        assert plan.tts_emotion == "calm"


class TestOperatingModes:
    def setup_method(self):
        self.planner = EmotionAwareResponsePlanner()

    def test_child_safe_mode_overrides_gesture(self):
        plan_normal = self.planner.plan("neutral", operating_mode="normal")
        plan_child  = self.planner.plan("neutral", operating_mode="child_safe")
        # Child safe should use greeting_pose override
        assert plan_child.gesture_name == "greeting_pose"

    def test_elderly_mode_slows_speech(self):
        plan = self.planner.plan("neutral", operating_mode="elderly")
        assert plan.tts_speed_scale <= 0.85

    def test_normal_mode_standard_speed(self):
        plan = self.planner.plan("happy", operating_mode="normal")
        assert abs(plan.tts_speed_scale - 1.0) < 0.05


class TestSupportedEmotions:
    def test_all_supported_emotions_have_plans(self):
        planner = EmotionAwareResponsePlanner()
        for emotion in planner.all_supported_emotions():
            plan = planner.plan(emotion, emotion_confidence=0.9)
            assert isinstance(plan, ResponsePlan)
            assert plan.tts_emotion in ("neutral", "warm", "concerned", "urgent", "calm")
