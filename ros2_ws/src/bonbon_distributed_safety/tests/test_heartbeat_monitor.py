"""Tests for HeartbeatMonitor — peer liveness must default to LOST until
proven otherwise, and transitions must fire exactly once per state change."""

from __future__ import annotations

import unittest

from bonbon_distributed_safety.core.heartbeat_monitor import (
    HeartbeatConfig,
    HeartbeatMonitor,
    PiId,
    PiLinkState,
)


class TestHeartbeatMonitor(unittest.TestCase):
    def setUp(self):
        self.cfg = HeartbeatConfig(stale_after_sec=1.5, lost_after_sec=5.0)
        self.mon = HeartbeatMonitor(PiId.PI3, [PiId.PI1, PiId.PI2], self.cfg)

    def test_never_seen_peer_is_lost(self):
        self.assertEqual(self.mon.state_of(PiId.PI1, now=0.0), PiLinkState.LOST)
        self.assertEqual(self.mon.state_of(PiId.PI2, now=0.0), PiLinkState.LOST)

    def test_recent_heartbeat_is_online(self):
        self.mon.on_heartbeat(PiId.PI1, now=10.0)
        self.assertEqual(self.mon.state_of(PiId.PI1, now=10.2), PiLinkState.ONLINE)

    def test_stale_after_threshold(self):
        self.mon.on_heartbeat(PiId.PI1, now=10.0)
        self.assertEqual(self.mon.state_of(PiId.PI1, now=11.6), PiLinkState.STALE)

    def test_lost_after_threshold(self):
        self.mon.on_heartbeat(PiId.PI1, now=10.0)
        self.assertEqual(self.mon.state_of(PiId.PI1, now=15.1), PiLinkState.LOST)

    def test_evaluate_returns_transition_on_first_online(self):
        self.mon.on_heartbeat(PiId.PI1, now=1.0)
        transitions = self.mon.evaluate(now=1.0)
        pi1_transitions = [t for t in transitions if t.pi == PiId.PI1]
        self.assertEqual(len(pi1_transitions), 1)
        self.assertEqual(pi1_transitions[0].previous_state, PiLinkState.LOST)
        self.assertEqual(pi1_transitions[0].new_state, PiLinkState.ONLINE)

    def test_evaluate_is_idempotent_with_no_state_change(self):
        self.mon.on_heartbeat(PiId.PI1, now=1.0)
        self.mon.evaluate(now=1.0)
        transitions = self.mon.evaluate(now=1.2)  # still ONLINE, no new heartbeat
        self.assertEqual([t for t in transitions if t.pi == PiId.PI1], [])

    def test_evaluate_detects_online_to_lost_transition(self):
        self.mon.on_heartbeat(PiId.PI2, now=1.0)
        self.mon.evaluate(now=1.0)
        transitions = self.mon.evaluate(now=10.0)  # well past lost_after_sec
        pi2_transitions = [t for t in transitions if t.pi == PiId.PI2]
        self.assertEqual(len(pi2_transitions), 1)
        self.assertEqual(pi2_transitions[0].new_state, PiLinkState.LOST)

    def test_recovery_after_loss_produces_transition(self):
        self.mon.on_heartbeat(PiId.PI1, now=1.0)
        self.mon.evaluate(now=1.0)
        self.mon.evaluate(now=10.0)  # -> LOST
        self.mon.on_heartbeat(PiId.PI1, now=10.1)
        transitions = self.mon.evaluate(now=10.1)
        pi1_transitions = [t for t in transitions if t.pi == PiId.PI1]
        self.assertEqual(len(pi1_transitions), 1)
        self.assertEqual(pi1_transitions[0].previous_state, PiLinkState.LOST)
        self.assertEqual(pi1_transitions[0].new_state, PiLinkState.ONLINE)

    def test_snapshot_covers_all_peers(self):
        self.mon.on_heartbeat(PiId.PI1, now=1.0)
        snap = self.mon.snapshot(now=1.0)
        self.assertEqual(set(snap.keys()), {PiId.PI1, PiId.PI2})
        self.assertEqual(snap[PiId.PI1], PiLinkState.ONLINE)
        self.assertEqual(snap[PiId.PI2], PiLinkState.LOST)

    def test_self_is_not_a_monitored_peer(self):
        self.assertNotIn(PiId.PI3, self.mon.peers)

    def test_heartbeat_from_unmonitored_pi_raises(self):
        with self.assertRaises(ValueError):
            self.mon.on_heartbeat(PiId.PI3, now=1.0)

    def test_invalid_config_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            HeartbeatConfig(stale_after_sec=5.0, lost_after_sec=1.0)


if __name__ == "__main__":
    unittest.main()
