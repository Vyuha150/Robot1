"""Tests for bonbon_data_pipeline.dataset_registry against the real
config/data/dataset_registry.yaml -- not just synthetic fixtures, so a
broken real config fails these tests, not just a hand-crafted example."""

from __future__ import annotations

from pathlib import Path

import pytest

from bonbon_data_pipeline.dataset_registry import DatasetEntry, DatasetRegistry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "config" / "data" / "dataset_registry.yaml"


@pytest.fixture
def registry() -> DatasetRegistry:
    return DatasetRegistry.load(_REGISTRY_PATH)


class TestRealConfigLoads:
    def test_loads_without_error(self, registry):
        assert len(registry.all()) > 0

    def test_validate_is_clean(self, registry):
        assert registry.validate() == []

    def test_every_capability_from_the_brief_has_at_least_one_dataset(self, registry):
        for capability in ("asr", "tts", "object_detection", "gesture_recognition", "navigation", "hospital_knowledge_rag"):
            assert registry.by_capability(capability), f"no dataset registered for {capability}"

    def test_at_least_one_blocked_dataset_exists(self, registry):
        # Real evidence that BLOCKED is actually reachable, not a status
        # value that only exists in the type signature.
        assert registry.by_status("BLOCKED")


class TestDatasetEntryValidation:
    def test_missing_required_field_raises(self):
        with pytest.raises(ValueError, match="missing required fields"):
            DatasetEntry.from_dict("bad_entry", {"name": "x"})

    def test_from_dict_to_dict_roundtrip_preserves_status(self):
        entry = DatasetEntry.from_dict(
            "x",
            {
                "name": "X", "source_url": "http://x", "capability": "asr", "domain": "english",
                "license": "MIT", "commercial_allowed": "true", "privacy_risk": "none",
                "download_allowed": True, "intended_use": "test", "prohibited_use": "",
                "preprocessing_needed": "", "target_model": "m", "evaluation_metric": "wer",
                "edge_export_format": "onnx", "status": "APPROVED",
            },
        )
        assert entry.to_dict()["status"] == "APPROVED"


class TestRegistryValidateCatchesBrokenConfig:
    def test_unknown_capability_is_flagged(self):
        registry = DatasetRegistry({
            "bad": DatasetEntry(
                dataset_id="bad", name="Bad", source_url="", capability="not_a_real_capability",
                domain="x", license="MIT", commercial_allowed="true", privacy_risk="none",
                download_allowed=False, intended_use="", prohibited_use="", preprocessing_needed="",
                target_model="", evaluation_metric="", edge_export_format="onnx", status="APPROVED",
            )
        })
        problems = registry.validate()
        assert any("unknown capability" in p for p in problems)

    def test_approved_with_unknown_license_is_flagged(self):
        registry = DatasetRegistry({
            "bad": DatasetEntry(
                dataset_id="bad", name="Bad", source_url="", capability="asr",
                domain="x", license="unknown", commercial_allowed="true", privacy_risk="none",
                download_allowed=False, intended_use="", prohibited_use="", preprocessing_needed="",
                target_model="", evaluation_metric="", edge_export_format="onnx", status="APPROVED",
            )
        })
        problems = registry.validate()
        assert any("license is unknown" in p for p in problems)
