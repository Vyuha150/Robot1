"""Tests for DistributedStatusTracker -- Pi-1's live view of Pi-2/Pi-3."""

from __future__ import annotations

import unittest

from bonbon_operator_api.ros2.distributed_status_tracker import (
    DistributedStatusTracker,
    LinkState,
)


class TestDistributedStatusTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = DistributedStatusTracker()

    def test_never_seen_pi_is_lost(self):
        self.assertEqual(self.tracker.link_state("pi2", now=0.0), LinkState.LOST)

    def test_recent_heartbeat_is_online(self):
        self.tracker.record_heartbeat("pi2", now=10.0)
        self.assertEqual(self.tracker.link_state("pi2", now=10.2), LinkState.ONLINE)

    def test_stale_after_threshold(self):
        self.tracker.record_heartbeat("pi3", now=10.0)
        self.assertEqual(self.tracker.link_state("pi3", now=11.6), LinkState.STALE)

    def test_lost_after_threshold(self):
        self.tracker.record_heartbeat("pi3", now=10.0)
        self.assertEqual(self.tracker.link_state("pi3", now=15.1), LinkState.LOST)

    def test_unknown_pi_id_rejected(self):
        with self.assertRaises(ValueError):
            self.tracker.record_heartbeat("pi9", now=0.0)

    def test_snapshot_covers_all_three_pis(self):
        self.tracker.record_heartbeat("pi1", now=1.0)
        snap = self.tracker.snapshot(now=1.0)
        self.assertEqual(set(snap["pi_links"].keys()), {"pi1", "pi2", "pi3"})
        self.assertEqual(snap["pi_links"]["pi1"], "online")
        self.assertEqual(snap["pi_links"]["pi2"], "lost")

    def test_snapshot_has_no_approval_or_rejection_initially(self):
        snap = self.tracker.snapshot(now=0.0)
        self.assertIsNone(snap["last_approval"])
        self.assertIsNone(snap["last_rejection"])
        self.assertEqual(snap["approval_count"], 0)

    def test_record_approval_updates_snapshot_and_counter(self):
        self.tracker.record_approval({"decision": "approved", "event_id": "e1"})
        snap = self.tracker.snapshot(now=0.0)
        self.assertEqual(snap["last_approval"]["event_id"], "e1")
        self.assertEqual(snap["approval_count"], 1)

    def test_record_rejection_updates_snapshot_and_counter(self):
        self.tracker.record_rejection({"decision": "rejected", "rejection_reason": "x"})
        snap = self.tracker.snapshot(now=0.0)
        self.assertEqual(snap["last_rejection"]["rejection_reason"], "x")
        self.assertEqual(snap["rejection_count"], 1)

    def test_record_degraded_mode_updates_snapshot(self):
        self.tracker.record_degraded_mode({"is_degraded": True, "reason": "pi3_loses_pi2"})
        snap = self.tracker.snapshot(now=0.0)
        self.assertTrue(snap["last_degraded_mode"]["is_degraded"])

    def test_multiple_approvals_only_keep_latest_but_count_all(self):
        self.tracker.record_approval({"event_id": "e1"})
        self.tracker.record_approval({"event_id": "e2"})
        snap = self.tracker.snapshot(now=0.0)
        self.assertEqual(snap["last_approval"]["event_id"], "e2")
        self.assertEqual(snap["approval_count"], 2)


if __name__ == "__main__":
    unittest.main()
