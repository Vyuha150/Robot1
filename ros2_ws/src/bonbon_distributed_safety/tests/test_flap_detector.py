"""Tests for FlapDetector -- 3-Pi Phase 7 remainder. A peer that transitions
state repeatedly within a short window is a distinct, worse condition than
a single clean transition; this module tracks that rate as its own signal."""

from __future__ import annotations

import unittest

from bonbon_distributed_safety.core.flap_detector import FlapConfig, FlapDetector
from bonbon_distributed_safety.core.heartbeat_monitor import LinkTransition, PiId, PiLinkState


def _transition(pi: PiId, at: float, new_state: PiLinkState = PiLinkState.ONLINE) -> LinkTransition:
    return LinkTransition(pi=pi, previous_state=PiLinkState.LOST, new_state=new_state, at=at)


class TestFlapConfig(unittest.TestCase):
    def test_non_positive_window_rejected(self):
        with self.assertRaises(ValueError):
            FlapConfig(window_sec=0.0)

    def test_threshold_below_two_rejected(self):
        with self.assertRaises(ValueError):
            FlapConfig(flap_threshold=1)


class TestFlapDetector(unittest.TestCase):
    def setUp(self):
        self.cfg = FlapConfig(window_sec=60.0, flap_threshold=3)
        self.det = FlapDetector([PiId.PI1, PiId.PI2], config=self.cfg)

    def test_no_transitions_is_not_flapping(self):
        self.assertFalse(self.det.is_flapping(PiId.PI1, now=0.0))
        self.assertEqual(self.det.flap_count(PiId.PI1, now=0.0), 0)

    def test_single_transition_is_not_flapping(self):
        self.det.record_transition(_transition(PiId.PI1, at=10.0))
        self.assertFalse(self.det.is_flapping(PiId.PI1, now=10.1))

    def test_reaching_threshold_within_window_is_flapping(self):
        for t in (10.0, 20.0, 30.0):
            self.det.record_transition(_transition(PiId.PI1, at=t))
        self.assertTrue(self.det.is_flapping(PiId.PI1, now=31.0))
        self.assertEqual(self.det.flap_count(PiId.PI1, now=31.0), 3)

    def test_transitions_outside_window_are_pruned(self):
        self.det.record_transition(_transition(PiId.PI1, at=0.0))
        self.det.record_transition(_transition(PiId.PI1, at=5.0))
        self.det.record_transition(_transition(PiId.PI1, at=10.0))
        # All three within window at now=15 -> flapping.
        self.assertTrue(self.det.is_flapping(PiId.PI1, now=15.0))
        # Advance far enough that only the last transition remains in window.
        self.assertFalse(self.det.is_flapping(PiId.PI1, now=100.0))
        self.assertEqual(self.det.flap_count(PiId.PI1, now=100.0), 0)

    def test_peers_are_tracked_independently(self):
        for t in (10.0, 20.0, 30.0):
            self.det.record_transition(_transition(PiId.PI1, at=t))
        self.det.record_transition(_transition(PiId.PI2, at=10.0))
        self.assertTrue(self.det.is_flapping(PiId.PI1, now=31.0))
        self.assertFalse(self.det.is_flapping(PiId.PI2, now=31.0))

    def test_flapping_peers_lists_only_flapping(self):
        for t in (10.0, 20.0, 30.0):
            self.det.record_transition(_transition(PiId.PI1, at=t))
        self.det.record_transition(_transition(PiId.PI2, at=10.0))
        self.assertEqual(self.det.flapping_peers(now=31.0), [PiId.PI1])

    def test_unknown_peer_transition_is_still_recorded(self):
        """A transition for a peer not passed at construction time is
        tracked rather than raising -- HeartbeatMonitor is the source of
        truth for which peers exist; FlapDetector should not duplicate
        that validation and reject a peer HeartbeatMonitor legitimately
        reports on."""
        det = FlapDetector([PiId.PI1], config=self.cfg)
        det.record_transition(_transition(PiId.PI3, at=10.0))
        det.record_transition(_transition(PiId.PI3, at=20.0))
        det.record_transition(_transition(PiId.PI3, at=30.0))
        self.assertTrue(det.is_flapping(PiId.PI3, now=31.0))

    def test_window_sec_property_exposes_config(self):
        self.assertEqual(self.det.window_sec, 60.0)


if __name__ == "__main__":
    unittest.main()
