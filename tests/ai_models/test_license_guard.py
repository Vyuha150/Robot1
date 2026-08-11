"""Tests for bonbon_ai_model_registry.model_license_checker.LicenseChecker
-- the gate encoding rules 1-3: never fake availability, never download
without checking license+storage, never auto-download Sarvam/other gated
providers without confirmed official access."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestLicenseGuard(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.checker = LicenseChecker()

    def test_gated_sarvam_provider_blocked_with_no_access_checker_configured(self):
        entry = self.registry.get("asr_sarvam_edge")
        self.assertIsNotNone(entry)
        decision = self.checker.check(entry)
        self.assertFalse(decision.allowed, "an unconfigured gated provider must fail closed, never open")
        self.assertIn("official-access check", decision.reason)

    def test_gated_sarvam_provider_blocked_when_access_checker_reports_false(self):
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker

        checker = LicenseChecker(access_checkers={"sarvam": lambda: False})
        entry = self.registry.get("asr_sarvam_edge")
        decision = checker.check(entry)
        self.assertFalse(decision.allowed)

    def test_gated_sarvam_provider_still_blocked_on_unknown_commercial_terms_even_with_access_confirmed(self):
        # Confirmed official access clears the provider-access gate, but
        # Sarvam's commercial_allowed is registered "unknown" (proprietary,
        # terms not independently verified) -- that is a SEPARATE gate
        # (rule 2) and must still block without a human's explicit_approval,
        # even once access is confirmed. Access != cleared commercial terms.
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker

        checker = LicenseChecker(access_checkers={"sarvam": lambda: True})
        entry = self.registry.get("asr_sarvam_edge")
        self.assertEqual(entry.commercial_allowed, "unknown")
        decision = checker.check(entry, explicit_approval=False)
        self.assertFalse(decision.allowed)
        self.assertIn("unknown", decision.reason)

    def test_gated_sarvam_provider_allowed_when_access_confirmed_and_explicitly_approved(self):
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker

        checker = LicenseChecker(access_checkers={"sarvam": lambda: True})
        entry = self.registry.get("asr_sarvam_edge")
        decision = checker.check(entry, explicit_approval=True)
        self.assertTrue(decision.allowed, decision.reason)

    def test_insightface_blocked_for_non_commercial_pretrained_weights(self):
        # face_insightface is registered commercial_allowed="false" -- its
        # pretrained weights are non-commercial per InsightFace's own terms.
        entry = self.registry.get("face_insightface")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.commercial_allowed, "false")
        decision = self.checker.check(entry)
        self.assertFalse(decision.allowed)
        self.assertIn("commercial use", decision.reason)

    def test_unknown_commercial_status_blocked_without_explicit_approval(self):
        entry = self.registry.get("vision_ultralytics_direct")  # AGPL-3.0, commercial_allowed=unknown
        self.assertIsNotNone(entry)
        self.assertEqual(entry.commercial_allowed, "unknown")
        decision = self.checker.check(entry, explicit_approval=False)
        self.assertFalse(decision.allowed)

    def test_unknown_commercial_status_allowed_with_explicit_approval(self):
        entry = self.registry.get("vision_ultralytics_direct")
        decision = self.checker.check(entry, explicit_approval=True)
        self.assertTrue(decision.allowed, decision.reason)

    def test_non_default_benchmark_only_llm_blocked_without_explicit_approval(self):
        # llm_qwen25_15b / llm_llama32_1b are registered but NOT
        # enabled_by_default -- rule: never auto-download a candidate model
        # without explicit approval.
        entry = self.registry.get("llm_qwen25_15b")
        self.assertIsNotNone(entry)
        self.assertFalse(entry.enabled_by_default)
        decision = self.checker.check(entry, explicit_approval=False)
        self.assertFalse(decision.allowed)

    def test_default_open_source_model_is_allowed(self):
        entry = self.registry.get("llm_qwen25_05b")  # Apache-2.0, enabled_by_default=True
        decision = self.checker.check(entry)
        self.assertTrue(decision.allowed, decision.reason)

    def test_oversized_download_blocked_without_explicit_approval(self):
        entry = self.registry.get("llm_qwen25_05b")
        oversized = replace(entry, expected_storage_mb=999_999)
        checker = self.checker
        decision = checker.check(oversized)
        self.assertFalse(decision.allowed)
        self.assertIn("exceeding", decision.reason)

    def test_unavailable_download_type_always_blocked(self):
        entry = self.registry.get("llm_qwen25_05b")
        unavailable = replace(entry, download_type="unavailable")
        decision = self.checker.check(unavailable, explicit_approval=True)  # even with approval
        self.assertFalse(decision.allowed)
        self.assertIn("no known source", decision.reason)


if __name__ == "__main__":
    unittest.main()
