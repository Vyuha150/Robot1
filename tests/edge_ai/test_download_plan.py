"""Edge AI Runtime brief Phase 13 -- download planning (Phase 11 rule: "do
not blindly download everything"). Covers the merged registry's
download_plan() honesty and that the 3 new capabilities' entries
(download_type="unavailable" -- deliberately no ML model, see
config/edge_ai/model_registry.yaml) are never auto-dispatched. Also
confirms every scripts/edge_ai/*.sh/*.py download/install script Phase
11 names actually exists on disk."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts" / "edge_ai"


class TestMergedRegistryDownloadPlan(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_downloader import ModelDownloader
        from bonbon_ai_model_registry.model_license_checker import LicenseChecker
        from bonbon_edge_ai_runtime.model_registry import load_merged

        self.registry = load_merged()
        self.downloader = ModelDownloader(LicenseChecker(), self.registry)

    def test_download_plan_covers_every_merged_entry(self):
        plan = self.downloader.download_plan()
        plan_ids = {row["modelId"] for row in plan}
        registry_ids = {e.model_id for e in self.registry.all()}
        self.assertEqual(plan_ids, registry_ids)

    def test_the_three_new_capabilities_are_never_auto_dispatched(self):
        # download_type="unavailable" for all 6 edge_ai-only entries --
        # none of them has a real ML model to fetch (deterministic
        # rule/fusion/guardrail logic, already present as application code).
        for entry in self.registry.all():
            if entry.capability not in ("human_state_fusion", "intent_classification", "assistant_guardrails"):
                continue
            result = self.downloader.download(entry.model_id, dry_run=False, explicit_approval=True)
            self.assertFalse(result.attempted, f"{entry.model_id} was auto-dispatched despite download_type=unavailable")
            self.assertFalse(result.succeeded)
            # The license checker itself rejects download_type="unavailable"
            # entries ("no known source exists") before dispatch is even
            # considered -- an even stronger guarantee than a dispatch-stage block.
            self.assertIn("unavailable", result.message)


class TestPhase11DownloadInstallScripts(unittest.TestCase):
    def test_every_named_script_exists(self):
        for name in (
            "download_qwen25_05b.sh",
            "install_sherpa_onnx.sh",
            "install_piper_tts.sh",
            "install_mediapipe.sh",
            "check_sarvam_access.py",
            "check_hailo_runtime.sh",
        ):
            path = _SCRIPTS_DIR / name
            self.assertTrue(path.is_file(), f"scripts/edge_ai/{name} is missing")


if __name__ == "__main__":
    unittest.main()
