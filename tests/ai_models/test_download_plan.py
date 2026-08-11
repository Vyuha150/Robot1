"""Tests for bonbon_ai_model_registry.model_downloader -- the
download-plan/print-before-download requirement, and the "API downloads
are always dry_run" rule that api/ai_model_status_api.py's
POST /ai-models/download/{model_id} depends on."""

from __future__ import annotations

import unittest
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "models" / "model_registry.yaml"


class TestDownloadPlan(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_downloader import ModelDownloader
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.downloader = ModelDownloader(LicenseChecker(), self.registry)

    def test_download_plan_covers_every_registered_entry(self):
        plan = self.downloader.download_plan()
        plan_ids = {row["modelId"] for row in plan}
        registry_ids = {e.model_id for e in self.registry.all()}
        self.assertEqual(plan_ids, registry_ids)

    def test_download_plan_never_raises_for_gated_entries(self):
        # Sarvam/InsightFace/AGPL entries must produce a row explaining
        # wouldDownload=False, never an exception that would crash a
        # dashboard request.
        plan = self.downloader.download_plan()
        sarvam_row = next(r for r in plan if r["modelId"] == "asr_sarvam_edge")
        self.assertFalse(sarvam_row["wouldDownload"])
        self.assertTrue(sarvam_row["reason"])

    def test_download_plan_can_be_filtered_by_capability(self):
        plan = self.downloader.download_plan(capability="local_llm")
        self.assertTrue(plan)
        for row in plan:
            entry = self.registry.get(row["modelId"])
            self.assertEqual(entry.capability, "local_llm")

    def test_unknown_model_id_download_returns_not_attempted(self):
        result = self.downloader.download("does_not_exist_at_all", dry_run=True)
        self.assertFalse(result.attempted)
        self.assertFalse(result.succeeded)
        self.assertIn("unknown model_id", result.message)

    def test_download_default_dry_run_never_dispatches_a_real_command(self):
        # ModelDownloader.download() defaults to dry_run=True -- calling it
        # with the bare default must never touch subprocess/network for a
        # real, downloadable entry.
        result = self.downloader.download("llm_qwen25_05b")
        self.assertTrue(result.attempted)
        self.assertTrue(result.succeeded)
        self.assertIn("dry_run", result.message)

    def test_gated_provider_download_is_blocked_even_with_dry_run_false_requested(self):
        # Even if a caller asks for dry_run=False, the license checker
        # rejection must still win -- an unconfigured LicenseChecker() has
        # no sarvam access_checker, so this must never attempt anything.
        result = self.downloader.download("asr_sarvam_edge", dry_run=False)
        self.assertFalse(result.attempted)
        self.assertFalse(result.succeeded)
        self.assertIn("blocked by license checker", result.message)

    def test_manual_or_api_download_type_never_auto_dispatched(self):
        # Any entry whose download_type is not one of {ollama, pip, git,
        # wget} (e.g. a "manual"/"api" type) must report itself as not
        # auto-dispatchable, command printed but not run.
        manual_entries = [e for e in self.registry.all() if e.download_type not in ("ollama", "pip", "git", "wget", "unavailable")]
        for entry in manual_entries:
            if not entry.enabled_by_default:
                continue  # license checker would reject this before reaching the dispatch check
            result = self.downloader.download(entry.model_id, dry_run=False, explicit_approval=True)
            if result.attempted and result.succeeded:
                self.fail(f"{entry.model_id} (download_type={entry.download_type!r}) was auto-dispatched")


if __name__ == "__main__":
    unittest.main()
