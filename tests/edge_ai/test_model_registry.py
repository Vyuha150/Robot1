"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.model_registry.
Assertion 1: the merge is additive (39 base + 6 edge_ai = 45+ entries,
zero validation problems). Assertion 2: each of the 3 new capabilities
(human_state_fusion, intent_classification, assistant_guardrails) has
exactly one enabled-by-default entry and a working fallback."""

from __future__ import annotations

import unittest


class TestMergedRegistry(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.model_registry import load_merged

        self.registry = load_merged()

    def test_merge_is_additive_and_clean(self):
        self.assertGreaterEqual(len(self.registry.all()), 45)
        problems = self.registry.validate()
        self.assertEqual(problems, [], f"merged registry has validation problems: {problems}")

    def test_three_new_capabilities_present(self):
        capabilities = {e.capability for e in self.registry.all()}
        for cap in ("human_state_fusion", "intent_classification", "assistant_guardrails"):
            self.assertIn(cap, capabilities)

    def test_each_new_capability_has_exactly_one_default(self):
        for cap in ("human_state_fusion", "intent_classification", "assistant_guardrails"):
            defaults = [e for e in self.registry.all() if e.capability == cap and e.enabled_by_default]
            self.assertEqual(len(defaults), 1, f"{cap} has {len(defaults)} defaults, expected exactly 1")

    def test_each_new_capability_default_has_a_working_fallback(self):
        ids = {e.model_id for e in self.registry.all()}
        for cap in ("human_state_fusion", "intent_classification", "assistant_guardrails"):
            default = self.registry.default_for_capability(cap)
            self.assertIsNotNone(default)
            self.assertIsNotNone(default.fallback_model_id, f"{default.model_id} has no fallback")
            self.assertIn(default.fallback_model_id, ids)

    def test_original_16_capabilities_untouched_by_merge(self):
        # The merge must not shadow or duplicate any base-registry entry.
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        base = ModelRegistry.load(str((__import__("pathlib").Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml")))
        for entry in base.all():
            merged_entry = self.registry.get(entry.model_id)
            self.assertIsNotNone(merged_entry, f"{entry.model_id} missing from merged registry")
            self.assertEqual(merged_entry.capability, entry.capability)


if __name__ == "__main__":
    unittest.main()
