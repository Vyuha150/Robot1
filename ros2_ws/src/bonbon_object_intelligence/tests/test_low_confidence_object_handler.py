"""Tests for LowConfidenceObjectHandler -- the explicit
"never let low confidence trigger behavior" gate."""

from __future__ import annotations

import unittest

from bonbon_object_intelligence.core.low_confidence_object_handler import (
    ConfidenceState,
    LowConfidenceConfig,
    LowConfidenceObjectHandler,
)


class TestLowConfidenceObjectHandler(unittest.TestCase):
    def setUp(self):
        self.handler = LowConfidenceObjectHandler(
            LowConfidenceConfig(actionable_threshold=0.6, high_confidence_threshold=0.85)
        )

    def test_low_confidence_is_not_actionable(self):
        result = self.handler.assess(0.4)
        self.assertEqual(result.state, ConfidenceState.LOW)
        self.assertFalse(result.is_actionable)

    def test_just_above_actionable_threshold_is_actionable(self):
        result = self.handler.assess(0.61)
        self.assertEqual(result.state, ConfidenceState.NORMAL)
        self.assertTrue(result.is_actionable)

    def test_high_confidence_is_actionable_and_flagged_high(self):
        result = self.handler.assess(0.9)
        self.assertEqual(result.state, ConfidenceState.HIGH)
        self.assertTrue(result.is_actionable)

    def test_boundary_at_actionable_threshold_is_actionable(self):
        result = self.handler.assess(0.6)
        self.assertTrue(result.is_actionable)


if __name__ == "__main__":
    unittest.main()
