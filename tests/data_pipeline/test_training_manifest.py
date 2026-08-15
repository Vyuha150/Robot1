"""Tests for bonbon_data_pipeline.training_manifest against the real
config/data/training_targets.yaml + dataset_registry.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from bonbon_data_pipeline.dataset_registry import DatasetRegistry
from bonbon_data_pipeline.training_manifest import TrainingManifest, TrainingTarget

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGETS_PATH = _REPO_ROOT / "config" / "data" / "training_targets.yaml"
_REGISTRY_PATH = _REPO_ROOT / "config" / "data" / "dataset_registry.yaml"


@pytest.fixture
def manifest() -> TrainingManifest:
    return TrainingManifest.load(_TARGETS_PATH)


@pytest.fixture
def registry() -> DatasetRegistry:
    return DatasetRegistry.load(_REGISTRY_PATH)


class TestRealConfigLoads:
    def test_loads_without_error(self, manifest):
        assert len(manifest.all()) > 0

    def test_every_recommended_capability_from_phase5_has_a_target(self, manifest):
        for capability in ("asr", "tts", "object_detection", "gesture_recognition", "navigation", "hospital_knowledge_rag"):
            assert manifest.get(capability) is not None

    def test_no_target_declares_a_pi_as_the_training_machine(self, manifest, registry):
        # Rule 7, checked directly against the real config (not just the
        # validator logic in isolation).
        problems = manifest.validate_against_registry(registry)
        assert not any("edge board" in p for p in problems)


class TestValidateAgainstRegistry:
    def test_real_config_pair_reports_no_unknown_dataset_ids(self, manifest, registry):
        problems = manifest.validate_against_registry(registry)
        assert not any("not found in dataset registry" in p for p in problems)

    def test_unknown_dataset_id_is_flagged(self, registry):
        manifest = TrainingManifest({
            "asr": TrainingTarget(
                capability="asr", baseline_model="m", dataset_ids=["does_not_exist"],
                training_machine="workstation_gpu", training_method="m",
                evaluation_metric="wer", acceptance_threshold=0.1,
                edge_export_format="onnx", rollback_plan="p",
            )
        })
        problems = manifest.validate_against_registry(registry)
        assert any("does_not_exist" in p and "not found" in p for p in problems)

    def test_pi_training_machine_is_flagged(self, registry):
        manifest = TrainingManifest({
            "asr": TrainingTarget(
                capability="asr", baseline_model="m", dataset_ids=["common_voice_en"],
                training_machine="raspberry_pi_3", training_method="m",
                evaluation_metric="wer", acceptance_threshold=0.1,
                edge_export_format="onnx", rollback_plan="p",
            )
        })
        problems = manifest.validate_against_registry(registry)
        assert any("edge board" in p for p in problems)

    def test_empty_dataset_ids_is_flagged(self, registry):
        manifest = TrainingManifest({
            "asr": TrainingTarget(
                capability="asr", baseline_model="m", dataset_ids=[],
                training_machine="workstation_gpu", training_method="m",
                evaluation_metric="wer", acceptance_threshold=0.1,
                edge_export_format="onnx", rollback_plan="p",
            )
        })
        problems = manifest.validate_against_registry(registry)
        assert any("no dataset_ids declared" in p for p in problems)


class TestResolveDatasets:
    def test_resolve_datasets_returns_real_entries(self, manifest, registry):
        entries = manifest.resolve_datasets("asr", registry)
        assert entries
        assert all(e.capability == "asr" for e in entries)

    def test_resolve_datasets_for_unknown_capability_returns_empty(self, manifest, registry):
        assert manifest.resolve_datasets("not_a_capability", registry) == []
