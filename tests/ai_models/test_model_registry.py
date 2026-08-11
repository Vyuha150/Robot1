"""Tests for bonbon_ai_model_registry.model_registry against the real,
checked-in config/models/model_registry.yaml -- these tests validate the
authored config itself, not a synthetic fixture, so a broken YAML edit
fails CI immediately rather than only being caught by a live dashboard
smoke test."""

from __future__ import annotations

import unittest
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestModelRegistryLoadsAndValidates(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import CAPABILITIES, ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.CAPABILITIES = CAPABILITIES

    def test_loads_at_least_39_entries(self):
        # 39 is the count documented in docs/AI_MODEL_FINAL_SELECTION_REPORT.md
        # as of this pass; a regression here means an edit silently dropped
        # entries rather than the count only ever growing.
        self.assertGreaterEqual(len(self.registry.all()), 39)

    def test_validate_reports_zero_problems(self):
        problems = self.registry.validate()
        self.assertEqual(problems, [], f"registry has real validation problems: {problems}")

    def test_every_entry_capability_is_known(self):
        for entry in self.registry.all():
            self.assertIn(entry.capability, self.CAPABILITIES, f"{entry.model_id} has unknown capability {entry.capability!r}")

    def test_every_fallback_model_id_exists(self):
        ids = {e.model_id for e in self.registry.all()}
        for entry in self.registry.all():
            if entry.fallback_model_id:
                self.assertIn(entry.fallback_model_id, ids, f"{entry.model_id} falls back to unknown {entry.fallback_model_id!r}")

    def test_at_most_one_enabled_default_per_capability(self):
        seen: dict[str, str] = {}
        for entry in self.registry.all():
            if not entry.enabled_by_default:
                continue
            self.assertNotIn(
                entry.capability, seen,
                f"capability {entry.capability!r} has two defaults: {seen.get(entry.capability)!r} and {entry.model_id!r}",
            )
            seen[entry.capability] = entry.model_id

    def test_qwen25_05b_is_the_local_llm_default(self):
        default = self.registry.default_for_capability("local_llm")
        self.assertIsNotNone(default)
        self.assertEqual(default.model_id, "llm_qwen25_05b")

    def test_fallback_chain_never_loops(self):
        # ModelRegistry.fallback_chain caps hop count defensively -- assert
        # that cap is never actually hit by any real chain in this registry
        # (a chain that long would indicate a cyclic fallback config).
        limit = len(self.registry.all()) + 1
        for entry in self.registry.all():
            chain = self.registry.fallback_chain(entry.model_id)
            self.assertLess(len(chain), limit, f"{entry.model_id}'s fallback chain looks cyclic")


class TestApplyProfileOverrides(unittest.TestCase):
    """Regression coverage for the offline_open_source_profile.yaml conflict
    found and fixed this session: flipping emotion_face_deepface/
    voice_emotion_speechbrain to enabled_by_default=true in the base
    registry created a duplicate-default conflict against that profile's
    old emotion_face_mock/voice_emotion_text_sentiment overrides."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_all_five_hardware_profiles_validate_clean(self):
        import yaml

        profiles = [
            "pi_ai_hat_plus_2_profile.yaml",
            "pi_cpu_fallback_profile.yaml",
            "sarvam_edge_profile.yaml",
            "offline_open_source_profile.yaml",
            "degraded_no_ai_profile.yaml",
        ]
        for name in profiles:
            path = REGISTRY_PATH.parent / name
            self.assertTrue(path.exists(), f"{name} is missing")
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            overridden = self.registry.apply_profile_overrides(data.get("overrides", {}))
            problems = overridden.validate()
            self.assertEqual(problems, [], f"{name} produces validation problems: {problems}")

    def test_apply_profile_overrides_never_mutates_base_registry(self):
        before = self.registry.default_for_capability("local_llm").model_id
        self.registry.apply_profile_overrides({"llm_qwen25_05b": False})
        after = self.registry.default_for_capability("local_llm").model_id
        self.assertEqual(before, after, "apply_profile_overrides must return a new registry, not mutate self")


if __name__ == "__main__":
    unittest.main()
