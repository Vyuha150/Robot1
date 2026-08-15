"""Required test 1: unknown license blocks dataset use.
Required test 2: commercial-disallowed dataset blocks production training.
Plus rule 5 (safety-relevant capability needs explicit safety verification)
and the privacy_risk -> privacy_guard clearance gate.
"""

from __future__ import annotations

from pathlib import Path

from bonbon_data_pipeline.dataset_license_checker import DatasetLicenseChecker
from bonbon_data_pipeline.dataset_registry import DatasetEntry, DatasetRegistry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "config" / "data" / "dataset_registry.yaml"


def _entry(**overrides) -> DatasetEntry:
    defaults = dict(
        dataset_id="ds", name="DS", source_url="http://x", capability="asr", domain="english",
        license="MIT", commercial_allowed="true", privacy_risk="none", download_allowed=True,
        intended_use="", prohibited_use="", preprocessing_needed="", target_model="",
        evaluation_metric="", edge_export_format="onnx", status="APPROVED",
    )
    defaults.update(overrides)
    return DatasetEntry(**defaults)


class TestRequiredBehavior1UnknownLicenseBlocks:
    def test_unknown_license_string_blocks(self):
        decision = DatasetLicenseChecker().check(_entry(license="unknown"))
        assert decision.allowed is False
        assert "unlicensed" in decision.reason or "unknown" in decision.reason

    def test_empty_license_blocks(self):
        decision = DatasetLicenseChecker().check(_entry(license=""))
        assert decision.allowed is False

    def test_known_permissive_license_is_allowed(self):
        decision = DatasetLicenseChecker().check(_entry(license="CC0-1.0", commercial_allowed="true"))
        assert decision.allowed is True


class TestRequiredBehavior2CommercialDisallowedBlocksProduction:
    def test_commercial_false_blocks_production_training(self):
        decision = DatasetLicenseChecker().check(
            _entry(commercial_allowed="false"), production_training=True
        )
        assert decision.allowed is False
        assert "commercial" in decision.reason

    def test_commercial_false_allowed_for_non_production_research_use(self):
        decision = DatasetLicenseChecker().check(
            _entry(commercial_allowed="false"), production_training=False
        )
        assert decision.allowed is True

    def test_commercial_unknown_always_blocks_without_explicit_approval(self):
        decision = DatasetLicenseChecker().check(_entry(commercial_allowed="unknown"))
        assert decision.allowed is False

    def test_real_registry_blocked_gesture_dataset_is_actually_blocked(self):
        # public_gesture_dataset_jester is CC BY-NC-SA 4.0 -- a real,
        # non-hypothetical example of this rule firing.
        registry = DatasetRegistry.load(_REGISTRY_PATH)
        jester = registry.get("public_gesture_dataset_jester")
        assert jester is not None
        decision = DatasetLicenseChecker().check(jester, production_training=True)
        assert decision.allowed is False


class TestRule5SafetyVerification:
    def test_navigation_dataset_blocked_for_production_without_safety_verification(self):
        decision = DatasetLicenseChecker().check(
            _entry(capability="navigation", status="APPROVED"), production_training=True
        )
        assert decision.allowed is False
        assert "safety" in decision.reason.lower()

    def test_navigation_dataset_allowed_once_safety_verified(self):
        decision = DatasetLicenseChecker().check(
            _entry(capability="navigation", status="APPROVED"),
            production_training=True,
            safety_verified=True,
        )
        assert decision.allowed is True

    def test_non_safety_capability_does_not_require_safety_verification(self):
        decision = DatasetLicenseChecker().check(
            _entry(capability="asr", status="APPROVED"), production_training=True
        )
        assert decision.allowed is True


class TestPrivacyClearanceGate:
    def test_raw_media_dataset_blocked_without_privacy_clearance(self):
        decision = DatasetLicenseChecker().check(_entry(privacy_risk="contains_raw_face_images"))
        assert decision.allowed is False

    def test_raw_media_dataset_allowed_once_privacy_cleared(self):
        decision = DatasetLicenseChecker().check(
            _entry(privacy_risk="contains_raw_face_images"), privacy_cleared=True
        )
        assert decision.allowed is True


class TestBlockedStatusAlwaysBlocks:
    def test_blocked_status_blocks_even_with_every_other_flag_true(self):
        decision = DatasetLicenseChecker().check(
            _entry(status="BLOCKED"),
            production_training=True,
            explicit_approval=True,
            privacy_cleared=True,
            safety_verified=True,
        )
        assert decision.allowed is False
