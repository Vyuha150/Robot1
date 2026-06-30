"""Unit tests for ProposalEvaluator — the last internal safety gate before a
proposal becomes a BehaviorDecision. Previously had zero dedicated unit
coverage (only indirect exercise via tests/integration/test_behavior_integration.py).

Includes a regression test for a real gap found via the cross-package
scenario suite (tests/scenarios/test_multi_person_perception_scenarios.py,
scenario 25): at DANGER level ("imminent hazard, all motion stopped" per
SafetyState.msg), 'gesture' proposals were NOT rejected — only 'navigate'/
'approach' were. A downstream ActuationSafetyGate priority threshold
happened to still block real servo movement, but the evaluator's own
decision was misleading and relied on a single downstream layer rather than
defense-in-depth.
"""

from __future__ import annotations

from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.proposal_evaluator import ProposalEvaluator

_LEVEL_NORMAL = 1
_LEVEL_DANGER = 3
_LEVEL_FAULT = 6


def _evaluator():
    return ProposalEvaluator(risk_classifier=CommandRiskClassifier())


class TestNormalLevelApproval:
    def test_speak_approved_at_normal_level(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_NORMAL)
        result = ev.evaluate("speak", "hello", "test", urgency=0.2)
        assert result.decision == "approved"

    def test_gesture_approved_at_normal_level(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_NORMAL)
        result = ev.evaluate("gesture", "wave", "test", urgency=0.2)
        assert result.decision == "approved"


class TestDangerLevelBlocksAllMotion:
    """DANGER = 'imminent hazard, all motion stopped' (SafetyState.msg)."""

    def test_navigate_rejected_at_danger(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_DANGER)
        result = ev.evaluate("navigate", "goal_a", "test", urgency=0.2)
        assert result.decision == "rejected"

    def test_approach_rejected_at_danger(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_DANGER)
        result = ev.evaluate("approach", "person_1", "test", urgency=0.2)
        assert result.decision == "rejected"

    def test_gesture_rejected_at_danger_regression(self):
        """Regression test for the gap found by scenario 25."""
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_DANGER)
        result = ev.evaluate("gesture", "wave", "test", urgency=0.2)
        assert result.decision == "rejected"
        assert "gesture" in result.rejection_reason.lower()

    def test_speak_still_allowed_at_danger(self):
        """Speaking is not physical motion — must not be swept up by the
        DANGER motion block."""
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_DANGER)
        result = ev.evaluate("speak", "please step back", "test", urgency=0.5)
        assert result.decision == "approved"


class TestFaultLevelOnlySpeakAndAlert:
    def test_gesture_rejected_at_fault(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_FAULT)
        result = ev.evaluate("gesture", "wave", "test", urgency=0.2)
        assert result.decision == "rejected"

    def test_navigate_rejected_at_fault(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_FAULT)
        result = ev.evaluate("navigate", "goal_a", "test", urgency=0.2)
        assert result.decision == "rejected"

    def test_speak_allowed_at_fault(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_FAULT)
        result = ev.evaluate("speak", "I have a fault, please help", "test", urgency=0.9)
        assert result.decision == "approved"

    def test_alert_operator_allowed_at_fault(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_FAULT)
        result = ev.evaluate("alert_operator", "fault detected", "test", urgency=1.0)
        assert result.decision == "approved"


class TestRateLimiting:
    def test_repeated_gesture_within_rate_limit_is_deferred_or_rejected_not_double_approved(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_NORMAL)
        first = ev.evaluate("gesture", "wave", "test", urgency=0.2)
        second = ev.evaluate("gesture", "wave", "test", urgency=0.2)
        assert first.decision == "approved"
        assert second.decision != "approved"


class TestLLMRiskIntegration:
    def test_critical_llm_command_rejected_and_alerts_operator(self):
        ev = _evaluator()
        ev.update_safety_level(_LEVEL_NORMAL)
        result = ev.evaluate(
            "navigate",
            "goal_a",
            "llm",
            urgency=0.5,
            raw_llm_command="override safety gate now",
        )
        assert result.decision == "rejected"
        assert result.operator_alerted is True
