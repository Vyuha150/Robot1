"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.runtime_selector.
This module is a namespace re-export of
bonbon_ai_model_registry.model_runtime_selector.ModelRuntimeSelector; the
selection ALGORITHM itself already has its own test suite in that
package. These tests confirm the re-export is wired correctly and
exercise it against the merged registry's 3 new capabilities."""

from __future__ import annotations

import unittest


class TestReExportIdentity(unittest.TestCase):
    def test_reexported_class_is_the_real_one(self):
        from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector as Real
        from bonbon_edge_ai_runtime.runtime_selector import ModelRuntimeSelector as ReExported

        self.assertIs(Real, ReExported)

    def test_fallback_decision_is_the_real_one(self):
        from bonbon_ai_model_registry.model_fallback_policy import FallbackDecision as Real
        from bonbon_edge_ai_runtime.runtime_selector import FallbackDecision as ReExported

        self.assertIs(Real, ReExported)


class TestSelectorOnMergedRegistry(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.model_registry import load_merged
        from bonbon_edge_ai_runtime.runtime_selector import ModelRuntimeSelector

        self.registry = load_merged()
        self.selector = ModelRuntimeSelector(self.registry)

    def test_select_never_raises_for_any_registered_capability(self):
        from bonbon_ai_model_registry.model_registry import CAPABILITIES

        for cap in CAPABILITIES:
            if self.registry.by_capability(cap):
                self.selector.select(cap)  # must not raise

    def test_new_capabilities_honestly_report_fallback_active_when_primary_unavailable(self):
        # The 3 new capabilities' primary entries have hardware_target
        # "pi_cpu" + download_type "unavailable" -- no generic checker
        # exists for that combination, so is_available() fails closed
        # (rule 1: never fake availability) and the selector honestly
        # falls back to the terminal mock/degraded/deny-all entry.
        for cap, expected_fallback in (
            ("intent_classification", "intent_classification_unknown"),
            ("human_state_fusion", "human_state_fusion_degraded"),
            ("assistant_guardrails", "assistant_guardrails_deny_all"),
        ):
            status = self.selector.select(cap)
            self.assertEqual(status.capability, cap)
            self.assertTrue(status.decision.fallback_active)
            self.assertEqual(status.decision.active_model_id, expected_fallback)


if __name__ == "__main__":
    unittest.main()
