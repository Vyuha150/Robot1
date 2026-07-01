"""Tests for ObjectVerificationManager -- an alias label is never trusted
off a single frame, and the "child" geometry heuristic behaves honestly."""

from __future__ import annotations

import unittest

from bonbon_object_intelligence.core.object_class_registry import ObjectClassRegistry
from bonbon_object_intelligence.core.object_verification_manager import (
    ObjectVerificationManager,
    VerificationConfig,
)


class TestObjectVerificationManager(unittest.TestCase):
    def setUp(self):
        self.registry = ObjectClassRegistry()
        self.mgr = ObjectVerificationManager(
            self.registry, VerificationConfig(min_consecutive_frames=3)
        )

    def test_single_frame_never_confirms_alias(self):
        results = self.mgr.verify("t1", "person", bbox=(0, 0, 50, 100), frame_height=400)
        child = next(r for r in results if r.reported_class in ("child", "person"))
        self.assertFalse(child.confirmed)

    def test_persistence_plus_geometry_confirms_child(self):
        for _ in range(3):
            results = self.mgr.verify("t1", "person", bbox=(0, 0, 50, 100), frame_height=400)
        child = next(r for r in results if r.evidence_frames >= 3)
        self.assertTrue(child.confirmed)
        self.assertEqual(child.reported_class, "child")

    def test_tall_bbox_never_confirms_child_even_with_persistence(self):
        for _ in range(5):
            results = self.mgr.verify("t1", "person", bbox=(0, 0, 50, 380), frame_height=400)
        child = results[0]
        self.assertFalse(child.confirmed)
        self.assertEqual(child.reported_class, "person")

    def test_reset_track_clears_evidence(self):
        for _ in range(3):
            self.mgr.verify("t1", "person", bbox=(0, 0, 50, 100), frame_height=400)
        self.mgr.reset_track("t1")
        results = self.mgr.verify("t1", "person", bbox=(0, 0, 50, 100), frame_height=400)
        self.assertEqual(results[0].evidence_frames, 1)

    def test_non_alias_base_class_returns_empty(self):
        results = self.mgr.verify("t1", "bottle", bbox=(0, 0, 20, 30), frame_height=400)
        self.assertEqual(results, [])

    def test_persistence_only_alias_confirmed_at_lower_confidence(self):
        cfg = VerificationConfig(min_consecutive_frames=2)
        mgr = ObjectVerificationManager(self.registry, cfg)
        for _ in range(2):
            results = mgr.verify("t2", "bed", bbox=(0, 0, 100, 100), frame_height=400)
        hospital_bed = next(
            r for r in results if r.reported_class == "hospital_bed" or not r.confirmed
        )
        self.assertTrue(hospital_bed.confirmed)
        self.assertLess(hospital_bed.confidence, cfg.geometry_confirmed_confidence)

    def test_pluggable_verifier_overrides_heuristic(self):
        cfg = VerificationConfig(
            min_consecutive_frames=1, verifier_fn=lambda target, base, bbox: 0.95
        )
        mgr = ObjectVerificationManager(self.registry, cfg)
        results = mgr.verify("t3", "person", bbox=(0, 0, 50, 380), frame_height=400)
        child = results[0]
        self.assertTrue(child.confirmed)
        self.assertEqual(child.confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
