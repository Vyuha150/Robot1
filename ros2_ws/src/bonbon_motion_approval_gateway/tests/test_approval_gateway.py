"""Tests for MotionApprovalGateway — the sole Pi-3 authority over movement
proposals. Every test name states the safety property it protects."""

from __future__ import annotations

import unittest

from bonbon_motion_approval_gateway.core.approval_gateway import (
    MotionApprovalGateway,
    ProposalInput,
    SafetyContext,
)


def _proposal(**overrides) -> ProposalInput:
    defaults = dict(
        event_id="ev-1",
        source_module="llm",
        person_id="p1",
        proposal_type="speak",
        proposal_content="hello",
        urgency=0.1,
        justification="greeting",
    )
    defaults.update(overrides)
    return ProposalInput(**defaults)


def _safety(**overrides) -> SafetyContext:
    defaults = dict(
        state_name="NORMAL",
        actuation_permitted=True,
        navigation_permitted=True,
        max_velocity_mps=0.5,
        requires_manual_reset=False,
    )
    defaults.update(overrides)
    return SafetyContext(**defaults)


class TestMotionApprovalGateway(unittest.TestCase):
    def setUp(self):
        self.gw = MotionApprovalGateway()

    def test_normal_state_speak_is_approved(self):
        d = self.gw.evaluate(_proposal(proposal_type="speak"), _safety())
        self.assertEqual(d.decision, "approved")
        self.assertTrue(d.safety_approved)
        self.assertTrue(d.logged)

    def test_navigate_rejected_when_navigation_not_permitted(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="navigate"),
            _safety(navigation_permitted=False, state_name="DANGER"),
        )
        self.assertEqual(d.decision, "rejected")
        self.assertIn("navigation not permitted", d.rejection_reason)

    def test_dock_type_also_requires_navigation_permitted(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="dock"), _safety(navigation_permitted=False, state_name="FAULT")
        )
        self.assertEqual(d.decision, "rejected")

    def test_manual_reset_required_blocks_non_safe_proposals(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="speak"),
            _safety(state_name="FAULT", requires_manual_reset=True),
        )
        self.assertEqual(d.decision, "rejected")
        self.assertIn("manual reset", d.rejection_reason)

    def test_manual_reset_required_still_allows_alert_operator(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="alert_operator"),
            _safety(state_name="FAULT", requires_manual_reset=True),
        )
        self.assertEqual(d.decision, "approved")

    def test_gesture_rejected_when_actuation_not_permitted(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="gesture"),
            _safety(actuation_permitted=False, state_name="DANGER"),
        )
        self.assertEqual(d.decision, "rejected")
        self.assertIn("actuation not permitted", d.rejection_reason)

    def test_gesture_approved_when_actuation_permitted(self):
        d = self.gw.evaluate(_proposal(proposal_type="gesture"), _safety(state_name="CAUTION"))
        self.assertEqual(d.decision, "approved")

    def test_unknown_proposal_type_never_silently_approved(self):
        d = self.gw.evaluate(_proposal(proposal_type="do_a_backflip"), _safety())
        self.assertEqual(d.decision, "rejected")
        self.assertIn("unrecognized", d.rejection_reason)
        self.assertTrue(d.logged)

    def test_high_urgency_in_danger_is_escalated_not_silently_rejected(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="speak", urgency=0.9), _safety(state_name="DANGER")
        )
        self.assertEqual(d.decision, "escalated")
        self.assertTrue(d.operator_alerted)

    def test_alert_operator_never_escalated_even_at_high_urgency_in_danger(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="alert_operator", urgency=0.95), _safety(state_name="DANGER")
        )
        self.assertEqual(d.decision, "approved")

    def test_operator_source_gets_no_special_bypass_in_danger(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="navigate", source_module="operator"),
            _safety(navigation_permitted=False, state_name="DANGER"),
        )
        self.assertEqual(d.decision, "rejected")

    def test_low_urgency_normal_state_approved_with_full_confidence(self):
        d = self.gw.evaluate(_proposal(urgency=0.05), _safety())
        self.assertEqual(d.decision, "approved")
        self.assertEqual(d.confidence, 1.0)

    def test_approved_motion_proposal_carries_velocity_cap_note(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="approach"), _safety(max_velocity_mps=0.3, state_name="CAUTION")
        )
        self.assertEqual(d.decision, "approved")
        self.assertIn("0.30", d.modification_note)

    def test_rejected_decision_always_has_nonempty_reason(self):
        d = self.gw.evaluate(
            _proposal(proposal_type="retreat"), _safety(navigation_permitted=False)
        )
        self.assertEqual(d.decision, "rejected")
        self.assertTrue(d.rejection_reason)

    def test_proposal_event_id_always_links_back_to_source(self):
        d = self.gw.evaluate(_proposal(event_id="ev-42"), _safety())
        self.assertEqual(d.proposal_event_id, "ev-42")


if __name__ == "__main__":
    unittest.main()
