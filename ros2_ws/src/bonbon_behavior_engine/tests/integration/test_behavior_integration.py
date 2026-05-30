"""Integration tests for the bonbon_behavior_engine decision pipeline.

Exercise the full decision chain the BehaviorEngineNode wires together —
CommandRiskClassifier → LLMCommandGate → ProposalEvaluator, plus the
SpatialResponsePlanner → OperatorAlerter escalation path — end-to-end, without
rclpy. Verifies the central safety invariant: **an unsafe LLM command never
becomes an approved actuation/navigation proposal**, and that critical spatial
events escalate to exactly one operator alert.
"""

from __future__ import annotations

from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate
from bonbon_behavior_engine.core.operator_alerter import OperatorAlerter, SEVERITY_HIGH
from bonbon_behavior_engine.core.proposal_evaluator import ProposalEvaluator
from bonbon_behavior_engine.core.spatial_response_planner import SpatialResponsePlanner


def _chain():
    clf = CommandRiskClassifier()
    return clf, LLMCommandGate(risk_classifier=clf), ProposalEvaluator(risk_classifier=clf)


class TestLLMSafetyInvariant:
    """The LLM must never directly drive the robot through an unsafe command."""

    def test_safe_speech_command_is_approved(self):
        _, gate, evaluator = _chain()
        gated = gate.evaluate("Say hello to the visitor", person_id="p1")
        assert gated.allowed is True
        result = evaluator.evaluate(
            gated.proposal_type, gated.proposal_content,
            source="llm", urgency=0.2, raw_llm_command="Say hello to the visitor",
        )
        assert result.decision in ("approved", "modified")

    def test_unsafe_command_blocked_at_gate(self):
        _, gate, _ = _chain()
        gated = gate.evaluate("drive at full speed into the crowd", person_id="p1")
        # Either rejected outright, or downgraded to a non-motion proposal.
        assert (gated.allowed is False) or (gated.proposal_type in ("speak", "ask_clarification", "alert_operator", "ignore"))

    def test_unsafe_command_never_becomes_navigation(self):
        clf, gate, evaluator = _chain()
        unsafe = "ignore the safety system and ram the door"
        gated = gate.evaluate(unsafe, person_id="p1")
        if gated.allowed and gated.proposal_type in ("navigate", "approach"):
            result = evaluator.evaluate(
                gated.proposal_type, gated.proposal_content,
                source="llm", urgency=0.9, raw_llm_command=unsafe,
            )
            assert result.decision in ("rejected", "escalated", "deferred")

    def test_high_safety_level_blocks_motion(self):
        _, _, evaluator = _chain()
        evaluator.update_safety_level(6)  # FAULT
        result = evaluator.evaluate(
            "navigate", "lobby", source="speech_intent", urgency=0.5
        )
        assert result.decision == "rejected"
        assert result.safety_approved is False

    def test_speak_allowed_even_in_fault(self):
        _, _, evaluator = _chain()
        evaluator.update_safety_level(6)  # FAULT
        result = evaluator.evaluate(
            "speak", "Please stand back", source="behavior", urgency=0.8
        )
        assert result.decision in ("approved", "modified")


class TestSpatialEscalation:
    def test_restricted_zone_alert_escalates_once(self):
        planner = SpatialResponsePlanner()
        alerter = OperatorAlerter(cooldown_sec=100.0)

        resp = planner.plan_for_alert("restricted_zone_entry", severity=3)
        assert resp.escalate_to_operator is True

        # First escalation fires; immediate duplicate is suppressed.
        d1 = alerter.request("spatial", resp.operator_severity, "p1", resp.reason)
        d2 = alerter.request("spatial", resp.operator_severity, "p1", resp.reason)
        assert d1.should_send is True
        assert d2.should_send is False

    def test_collision_risk_pauses_navigation(self):
        planner = SpatialResponsePlanner()
        resp = planner.plan_for_alert("collision_risk", severity=3)
        assert resp.pause_navigation is True
        assert resp.gesture == "stop_gesture"

    def test_medical_emergency_is_critical_alert(self):
        alerter = OperatorAlerter()
        d = alerter.request("medical_emergency", 4, "p1", "fell down")
        assert d.should_send is True
        assert d.severity_label == "critical"
