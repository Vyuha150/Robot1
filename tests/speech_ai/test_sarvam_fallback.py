"""Tests for bonbon_sarvam_adapter's license/fallback decision chain --
rule 3 (never download/use commercial Sarvam without official access) and
rule 4/12 (never use a cloud API by default; Sarvam is the preferred
Indic engine ONLY when Edge/API access is genuinely confirmed, and an API
key existing is not the same as being authorized to use it)."""

from __future__ import annotations

import unittest


class TestSarvamLicenseDecisionTable(unittest.TestCase):
    """Pure decision-table tests -- no env vars, no imports beyond the
    dataclass evaluator itself."""

    def setUp(self):
        from bonbon_sarvam_adapter.sarvam_license_status import evaluate

        self.evaluate = evaluate

    def test_edge_installed_is_always_allowed_regardless_of_api_key(self):
        status = self.evaluate(edge_installed=True, api_key_present=False, cloud_enabled=False)
        self.assertTrue(status.allowed)
        self.assertEqual(status.mode, "edge")

    def test_api_key_with_cloud_enabled_is_allowed(self):
        status = self.evaluate(edge_installed=False, api_key_present=True, cloud_enabled=True)
        self.assertTrue(status.allowed)
        self.assertEqual(status.mode, "api")

    def test_api_key_without_cloud_enabled_is_NOT_allowed(self):
        # This is the rule-4 case: an API key existing in the environment
        # must never be silently treated as authorization to call a cloud
        # API by default.
        status = self.evaluate(edge_installed=False, api_key_present=True, cloud_enabled=False)
        self.assertFalse(status.allowed)
        self.assertEqual(status.mode, "unavailable")
        self.assertIn("rule 4", status.reason)

    def test_neither_edge_nor_api_key_is_not_allowed(self):
        status = self.evaluate(edge_installed=False, api_key_present=False, cloud_enabled=False)
        self.assertFalse(status.allowed)
        self.assertEqual(status.mode, "unavailable")

    def test_edge_takes_priority_over_api_key_state(self):
        # Edge installed should short-circuit to allowed=True/mode=edge
        # even if cloud_enabled is False -- edge is local, no cloud call.
        status = self.evaluate(edge_installed=True, api_key_present=True, cloud_enabled=False)
        self.assertTrue(status.allowed)
        self.assertEqual(status.mode, "edge")


class TestSarvamCapabilityDetectorOnThisSandbox(unittest.TestCase):
    """This sandbox has no Sarvam Edge package installed and no
    SARVAM_API_KEY -- detect_sarvam_capabilities() must honestly report
    every capability False, never optimistically assumed."""

    def setUp(self):
        import os

        self._saved_env = {k: os.environ.get(k) for k in ("SARVAM_API_KEY", "BONBON_CLOUD_ENABLED", "SARVAM_OCR_ENABLED")}
        for k in self._saved_env:
            os.environ.pop(k, None)

    def tearDown(self):
        import os

        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_capabilities_all_false_with_no_access_configured(self):
        from bonbon_sarvam_adapter.sarvam_capability_detector import detect_sarvam_capabilities

        caps = detect_sarvam_capabilities()
        self.assertFalse(caps.available)
        self.assertFalse(caps.asr_available)
        self.assertFalse(caps.tts_available)
        self.assertFalse(caps.translation_available)
        self.assertTrue(caps.fallback_active)

    def test_api_key_alone_without_cloud_flag_still_reports_unavailable(self):
        import os

        os.environ["SARVAM_API_KEY"] = "fake-test-key-not-real"
        from bonbon_sarvam_adapter.sarvam_capability_detector import detect_sarvam_capabilities

        caps = detect_sarvam_capabilities()
        self.assertFalse(caps.available, "an API key alone (without BONBON_CLOUD_ENABLED=true) must never enable Sarvam")

    def test_bespoke_availability_checker_matches_the_capability_detector(self):
        from bonbon_sarvam_adapter.sarvam_fallback_policy import bespoke_availability_checker

        checker = bespoke_availability_checker("asr")
        self.assertFalse(checker(None), "must return False (not raise) when Sarvam is genuinely unavailable")


if __name__ == "__main__":
    unittest.main()
