"""GAP-E6 fix (docs/EDGE_AI_GAP_ANALYSIS.md, docs/SAFETY_SEPARATION_AUDIT.md
Finding 7): before this file, no test exercised the actual topic-graph
chain GAP-E1/E2/E3 fixed -- each package's tests covered its own pure
logic in isolation, but nothing proved the three pieces compose
correctly end to end.

This test chains the REAL pure decision functions each node in the real
chain actually calls, in the real order the real topic graph invokes
them, with no mocks of the safety-decision logic itself:

  BehaviorRecommendation
    -> bonbon_behavior_engine.core.behavior_recommendation_bridge.recommendation_to_proposal()
    -> bonbon_motion_approval_gateway.core.approval_gateway.MotionApprovalGateway.evaluate()
    -> bonbon_navigation.safety.approved_command_gate.should_dispatch_navigation()

A real ROS2 launch-graph test would additionally prove the topics are
wired correctly (this dev sandbox has no rclpy, so that layer cannot be
exercised here -- see docs/EDGE_AI_GAP_ANALYSIS.md GAP-E6 for that
residual gap). What this DOES newly prove, that no prior test did: the
three packages' pure decision functions compose to produce the right
end-to-end verdict, including the specific GAP-E1 scenario (no
navigation without a fresh, permitting SafetyState) and GAP-E2 scenario
(a behavior recommendation alone is never enough -- it must pass through
approval before a dispatch decision is even possible).
"""

from __future__ import annotations

import unittest

from bonbon_behavior_engine.core.behavior_recommendation_bridge import (
    recommendation_to_proposal,
)
from bonbon_motion_approval_gateway.core.approval_gateway import (
    MotionApprovalGateway,
    ProposalInput,
    SafetyContext,
)
from bonbon_navigation.safety.approved_command_gate import should_dispatch_navigation


def _run_chain(behavior_class, params, safety: SafetyContext, urgency_priority=1):
    """Full chain: BehaviorRecommendation-shaped input -> final
    should-we-dispatch-a-Nav2-goal verdict."""
    proposal_fields = recommendation_to_proposal(
        behavior_class, list(params.keys()), list(params.values()), confidence=0.9, priority=urgency_priority
    )
    if proposal_fields is None:
        return None, None  # bridge refused to produce a proposal at all

    proposal = ProposalInput(
        event_id="rec-1",
        source_module="llm",
        person_id="p1",
        proposal_type=proposal_fields.proposal_type,
        proposal_content=proposal_fields.proposal_content,
        urgency=proposal_fields.urgency,
        nav_goal_x=proposal_fields.nav_goal_x,
        nav_goal_y=proposal_fields.nav_goal_y,
        nav_goal_yaw=proposal_fields.nav_goal_yaw,
        nav_goal_label=proposal_fields.nav_goal_label,
    )
    gateway = MotionApprovalGateway(event_id_factory=lambda: "decision-1")
    decision = gateway.evaluate(proposal, safety)
    dispatch = should_dispatch_navigation(decision.decision, decision.approved_action)
    return decision, dispatch


_SAFETY_NORMAL = SafetyContext(
    state_name="NORMAL", actuation_permitted=True, navigation_permitted=True,
    max_velocity_mps=0.8, requires_manual_reset=False,
)
_SAFETY_DANGER = SafetyContext(
    state_name="DANGER", actuation_permitted=False, navigation_permitted=False,
    max_velocity_mps=0.0, requires_manual_reset=False,
)
_SAFETY_FAULT = SafetyContext(
    state_name="FAULT", actuation_permitted=False, navigation_permitted=False,
    max_velocity_mps=0.0, requires_manual_reset=True,
)


class TestEndToEndNavigationSafetyChain(unittest.TestCase):
    def test_navigate_to_goal_dispatches_under_normal_safety(self):
        decision, dispatch = _run_chain(
            "navigate_to_goal", {"goal_x": "3.0", "goal_y": "1.5", "named_location": "cardiology"},
            _SAFETY_NORMAL,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.decision, "approved")
        self.assertTrue(dispatch, "an approved navigate proposal under NORMAL safety must dispatch")
        self.assertEqual(decision.nav_goal_label, "cardiology")

    def test_navigate_to_goal_is_blocked_when_navigation_not_permitted(self):
        # GAP-E1 regression: this is the exact scenario the original
        # fail-open bug would have let through.
        decision, dispatch = _run_chain(
            "navigate_to_goal", {"goal_x": "3.0", "goal_y": "1.5"}, _SAFETY_DANGER,
        )
        self.assertEqual(decision.decision, "rejected")
        self.assertFalse(dispatch, "navigation must never dispatch when SafetyState forbids it")

    def test_navigate_to_goal_is_blocked_when_manual_reset_required(self):
        decision, dispatch = _run_chain(
            "navigate_to_goal", {"goal_x": "1.0", "goal_y": "1.0"}, _SAFETY_FAULT,
        )
        self.assertEqual(decision.decision, "rejected")
        self.assertFalse(dispatch)

    def test_approach_person_dispatches_under_normal_safety(self):
        decision, dispatch = _run_chain(
            "approach_person", {"goal_x": "0.5", "goal_y": "0.5"}, _SAFETY_NORMAL,
        )
        self.assertEqual(decision.decision, "approved")
        self.assertTrue(dispatch)

    def test_non_navigation_behavior_class_never_enters_the_approval_chain(self):
        # stop_navigation is a de-escalation handled directly by
        # navigation_node, not bridged into a proposal at all (see
        # behavior_recommendation_bridge.py's own docstring).
        decision, dispatch = _run_chain("stop_navigation", {}, _SAFETY_NORMAL)
        self.assertIsNone(decision)
        self.assertIsNone(dispatch)

    def test_unrecognized_behavior_class_never_produces_a_proposal(self):
        # A behavior class the bridge doesn't know must never be guessed
        # into a navigate/approach proposal -- absence of translation is
        # the safe default, matching rule 13.
        decision, dispatch = _run_chain("dance_happily", {}, _SAFETY_NORMAL)
        self.assertIsNone(decision)
        self.assertIsNone(dispatch)

    def test_malformed_goal_params_never_produce_a_proposal(self):
        decision, dispatch = _run_chain(
            "navigate_to_goal", {"goal_x": "not-a-number", "goal_y": "1.0"}, _SAFETY_NORMAL,
        )
        self.assertIsNone(decision)
        self.assertIsNone(dispatch)

    def test_high_urgency_navigate_in_danger_state_escalates_not_dispatches(self):
        decision, dispatch = _run_chain(
            "navigate_to_goal", {"goal_x": "1.0", "goal_y": "1.0"}, _SAFETY_DANGER, urgency_priority=3,
        )
        # DANGER + navigation_permitted=False rejects before urgency/
        # escalation is even considered -- rejected, not escalated, and
        # either way never dispatched.
        self.assertIn(decision.decision, ("rejected", "escalated"))
        self.assertFalse(dispatch)

    def test_approved_speak_action_never_triggers_navigation_dispatch(self):
        # A non-motion approval must never be mistaken for a dispatchable one.
        gateway = MotionApprovalGateway(event_id_factory=lambda: "decision-speak")
        proposal = ProposalInput(
            event_id="rec-2", source_module="llm", person_id="p1",
            proposal_type="speak", proposal_content="hello", urgency=0.1,
        )
        decision = gateway.evaluate(proposal, _SAFETY_NORMAL)
        self.assertEqual(decision.decision, "approved")
        self.assertFalse(should_dispatch_navigation(decision.decision, decision.approved_action))


if __name__ == "__main__":
    unittest.main()
