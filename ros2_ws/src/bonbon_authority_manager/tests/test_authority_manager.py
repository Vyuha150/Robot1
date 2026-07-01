"""Tests for AuthorityManager — verifies each Pi's role applies exactly the
failure_policy.yaml scenario for its situation, and never a different one."""

from __future__ import annotations

import unittest

from bonbon_authority_manager.core.authority_manager import AuthorityManager, SelfRole
from bonbon_distributed_safety.core.heartbeat_monitor import PiId, PiLinkState

_ALL_ONLINE = {
    PiId.PI1: PiLinkState.ONLINE,
    PiId.PI2: PiLinkState.ONLINE,
    PiId.PI3: PiLinkState.ONLINE,
}


class TestAuthorityManagerPi3(unittest.TestCase):
    def setUp(self):
        self.mgr = AuthorityManager(SelfRole.PI3_NAVIGATION_SAFETY)

    def test_nominal_when_all_online(self):
        snap = self.mgr.evaluate(_ALL_ONLINE)
        self.assertTrue(snap.motion_authority_available)
        self.assertTrue(snap.human_interaction_permitted)
        self.assertEqual(snap.degraded_modules, ())
        self.assertEqual(snap.policy_reason, "nominal")

    def test_pi1_loss_does_not_affect_pi3_at_all(self):
        states = dict(_ALL_ONLINE, **{PiId.PI1: PiLinkState.LOST})
        snap = self.mgr.evaluate(states)
        self.assertTrue(snap.motion_authority_available)
        self.assertTrue(snap.human_interaction_permitted)
        self.assertEqual(snap.policy_reason, "nominal")

    def test_pi2_loss_disables_human_interaction_but_not_motion(self):
        states = dict(_ALL_ONLINE, **{PiId.PI2: PiLinkState.LOST})
        snap = self.mgr.evaluate(states)
        self.assertTrue(snap.motion_authority_available)
        self.assertFalse(snap.human_interaction_permitted)
        self.assertIn("human_ai", snap.degraded_modules)
        self.assertEqual(snap.policy_reason, "pi3_loses_pi2")

    def test_pi2_stale_not_yet_lost_stays_nominal(self):
        states = dict(_ALL_ONLINE, **{PiId.PI2: PiLinkState.STALE})
        snap = self.mgr.evaluate(states)
        self.assertTrue(snap.human_interaction_permitted)
        self.assertEqual(snap.policy_reason, "nominal")


class TestAuthorityManagerPi1(unittest.TestCase):
    def setUp(self):
        self.mgr = AuthorityManager(SelfRole.PI1_UI_API)

    def test_nominal_when_all_online(self):
        snap = self.mgr.evaluate(_ALL_ONLINE)
        self.assertTrue(snap.motion_authority_available)
        self.assertEqual(snap.policy_reason, "nominal")

    def test_pi3_loss_marks_motion_authority_unavailable(self):
        states = dict(_ALL_ONLINE, **{PiId.PI3: PiLinkState.LOST})
        snap = self.mgr.evaluate(states)
        self.assertFalse(snap.motion_authority_available)
        self.assertIn("unreachable", snap.dashboard_message.lower())
        self.assertEqual(snap.policy_reason, "pi1_loses_pi3")

    def test_pi2_loss_does_not_affect_pi1_motion_authority_flag(self):
        states = dict(_ALL_ONLINE, **{PiId.PI2: PiLinkState.LOST})
        snap = self.mgr.evaluate(states)
        self.assertTrue(snap.motion_authority_available)
        self.assertEqual(snap.policy_reason, "nominal")


class TestAuthorityManagerPi2(unittest.TestCase):
    def setUp(self):
        self.mgr = AuthorityManager(SelfRole.PI2_HUMAN_AI)

    def test_nominal_when_all_online(self):
        snap = self.mgr.evaluate(_ALL_ONLINE)
        self.assertFalse(snap.should_pause_proposals)
        self.assertEqual(snap.policy_reason, "nominal")

    def test_pi3_loss_pauses_proposals_but_keeps_local_ai_running(self):
        states = dict(_ALL_ONLINE, **{PiId.PI3: PiLinkState.LOST})
        snap = self.mgr.evaluate(states)
        self.assertTrue(snap.should_pause_proposals)
        self.assertTrue(snap.human_interaction_permitted)  # local perception/LLM unaffected
        self.assertEqual(snap.policy_reason, "pi2_loses_pi3")


if __name__ == "__main__":
    unittest.main()
