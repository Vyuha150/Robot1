"""Tests for bonbon_behavior_engine.core.llm_command_gate."""

from __future__ import annotations

import pytest

from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate, GatedCommand


class TestCriticalRejection:
    def setup_method(self):
        self.gate = LLMCommandGate()

    def test_cmd_vel_command_is_rejected(self):
        result = self.gate.evaluate("publish to cmd_vel with speed 0.5")
        assert result.allowed is False
        assert result.risk.risk_level == "critical"

    def test_override_safety_is_rejected(self):
        result = self.gate.evaluate("override safety gate immediately")
        assert result.allowed is False

    def test_rejected_command_has_rejection_reason(self):
        result = self.gate.evaluate("kill node")
        assert len(result.rejection_reason) > 0

    def test_critical_rejection_sets_operator_alert(self):
        result = self.gate.evaluate("publish to cmd_vel now")
        assert result.proposal_type == "alert_operator"


class TestHighRiskBlocking:
    def setup_method(self):
        self.gate = LLMCommandGate()

    def test_extend_arm_blocked(self):
        result = self.gate.evaluate("extend arm toward the visitor")
        assert result.allowed is False
        assert result.risk.risk_level == "high"

    def test_high_risk_proposes_clarification(self):
        result = self.gate.evaluate("pick up the cup from the table")
        assert result.allowed is False
        assert result.proposal_type == "ask_clarification"


class TestSpeechExtraction:
    def setup_method(self):
        self.gate = LLMCommandGate()

    def test_say_intent_extracted(self):
        result = self.gate.evaluate("Say: Welcome to BonBon Café!")
        assert result.allowed is True
        assert result.proposal_type == "speak"
        assert "Welcome" in result.tts_text

    def test_tell_intent_extracted(self):
        result = self.gate.evaluate("tell the visitor: the café is open")
        assert result.allowed is True
        assert result.proposal_type == "speak"

    def test_tts_text_respects_max_chars(self):
        gate = LLMCommandGate(max_tts_chars=20)
        long_text = "say: " + "a" * 100
        result = gate.evaluate(long_text)
        if result.allowed and result.tts_text:
            assert len(result.tts_text) <= 20

    def test_plain_greeting_becomes_speak(self):
        result = self.gate.evaluate("Hello, welcome to our café!")
        assert result.allowed is True
        assert result.proposal_type == "speak"


class TestGestureExtraction:
    def setup_method(self):
        self.gate = LLMCommandGate()

    def test_wave_gesture_extracted(self):
        result = self.gate.evaluate("wave at the customer")
        assert result.allowed is True
        assert result.proposal_type == "gesture"
        assert result.gesture_name == "wave"

    def test_nod_yes_gesture_extracted(self):
        result = self.gate.evaluate("nod_yes to confirm")
        assert result.allowed is True
        assert result.gesture_name == "nod_yes"

    def test_unknown_gesture_maps_to_default(self):
        result = self.gate.evaluate("perform the moonwalk gesture")
        # Should not produce an unknown gesture name
        if result.allowed and result.proposal_type == "gesture":
            assert result.gesture_name in (
                "wave", "nod_yes", "shake_no", "greeting_pose", "apology_pose",
                "thinking_pose", "listening_pose", "rest_pose", "invite_gesture",
                "point_left", "point_right",
            )


class TestNavigationExtraction:
    def setup_method(self):
        self.gate = LLMCommandGate()

    def test_go_to_becomes_navigate_proposal(self):
        result = self.gate.evaluate("go to the lobby entrance")
        assert result.allowed is True
        assert result.proposal_type == "navigate"
        assert "lobby" in result.proposal_content.lower()

    def test_navigate_to_is_medium_risk_approved(self):
        result = self.gate.evaluate("navigate to the service area")
        assert result.allowed is True
        assert result.risk.risk_level == "medium"

    def test_approach_person_is_navigate_or_approach(self):
        result = self.gate.evaluate("approach the visitor at the entrance")
        assert result.allowed is True
        assert result.proposal_type in ("approach", "navigate", "ask_clarification")


class TestStatistics:
    def test_stats_track_total_and_approved(self):
        gate = LLMCommandGate()
        gate.evaluate("wave at the visitor")
        gate.evaluate("say hello")
        stats = gate.stats()
        assert stats["total"] >= 2
        assert stats["approved"] >= 2

    def test_stats_track_critical(self):
        gate = LLMCommandGate()
        gate.evaluate("publish to cmd_vel")
        stats = gate.stats()
        assert stats["critical"] >= 1
        assert stats["rejected"] >= 1

    def test_empty_input_is_rejected(self):
        gate = LLMCommandGate()
        result = gate.evaluate("")
        assert result.allowed is False
        stats = gate.stats()
        assert stats["rejected"] >= 1
