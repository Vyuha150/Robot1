"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.degraded_mode_manager.
EdgeDegradedModeManager bridges to the real, already-tested
bonbon_perception_efficiency.core.degraded_mode_manager.DegradedModeManager
and combines it with per-capability FallbackDecision.degraded reporting
-- these tests check the combination logic, not the underlying
perception-layer sustained-pressure detector itself."""

from __future__ import annotations

import unittest


class TestCombinedDegradedStatus(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.degraded_mode_manager import EdgeDegradedModeManager

        self.manager = EdgeDegradedModeManager(sustained_threshold_sec=0.0)

    def test_normal_load_no_safety_fault_no_capability_degraded(self):
        from bonbon_perception_efficiency.core.load_shedding_controller import LoadLevel

        status = self.manager.update(LoadLevel.NORMAL, safety_fault_or_above=False)
        self.assertFalse(status.perception_degraded)
        self.assertEqual(status.capabilities_degraded, {})
        self.assertFalse(status.to_dict()["anyDegraded"])

    def test_capability_fallback_decisions_with_degraded_true_are_surfaced(self):
        from bonbon_perception_efficiency.core.load_shedding_controller import LoadLevel

        class _FakeDecision:
            def __init__(self, degraded, reason):
                self.degraded = degraded
                self.reason = reason

        decisions = {
            "local_llm": _FakeDecision(degraded=True, reason="fell back to CPU-only fallback"),
            "asr": _FakeDecision(degraded=False, reason="primary model active"),
        }
        status = self.manager.update(LoadLevel.NORMAL, safety_fault_or_above=False, capability_fallback_decisions=decisions)
        self.assertEqual(status.capabilities_degraded, {"local_llm": "fell back to CPU-only fallback"})
        self.assertNotIn("asr", status.capabilities_degraded)
        self.assertTrue(status.to_dict()["anyDegraded"])

    def test_to_dict_has_all_required_fields(self):
        from bonbon_perception_efficiency.core.load_shedding_controller import LoadLevel

        status = self.manager.update(LoadLevel.NORMAL, safety_fault_or_above=False)
        as_dict = status.to_dict()
        for field in ("perceptionDegraded", "perceptionReason", "perceptionDurationSec", "capabilitiesDegraded", "anyDegraded"):
            self.assertIn(field, as_dict)

    def test_this_does_not_duplicate_the_real_perception_degraded_mode_manager(self):
        # Regression guard for the exact duplication docs/DUPLICATE_PIPELINE_AUDIT.md
        # flags: this module must delegate, not reimplement, sustained-pressure detection.
        import inspect

        from bonbon_edge_ai_runtime.degraded_mode_manager import EdgeDegradedModeManager

        source = inspect.getsource(EdgeDegradedModeManager)
        self.assertIn("bonbon_perception_efficiency.core.degraded_mode_manager", source)


if __name__ == "__main__":
    unittest.main()
