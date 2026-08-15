"""Required test 8: edge export target is selected correctly.
Required test 9: a rollback model remains available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bonbon_data_pipeline.export_for_edge import (
    EdgeDeploymentTracker,
    ExportTargetRegistry,
    RollbackUnavailableError,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGETS_PATH = _REPO_ROOT / "config" / "data" / "model_export_targets.yaml"


@pytest.fixture
def export_registry() -> ExportTargetRegistry:
    return ExportTargetRegistry.load(_TARGETS_PATH)


@pytest.fixture
def tracker(tmp_path) -> EdgeDeploymentTracker:
    return EdgeDeploymentTracker(tmp_path / "edge_deployments.json")


class TestRequiredBehavior8ExportTargetSelectedCorrectly:
    def test_real_config_loads_and_validates(self, export_registry):
        assert len(export_registry.all()) > 0
        assert export_registry.validate() == []

    def test_object_detection_selects_hailo_hef(self, export_registry):
        target = export_registry.get("object_detection")
        assert target is not None
        assert target.export_format == "hailo_hef"
        assert target.fallback_export_format == "onnx"

    def test_local_llm_selects_gguf_never_hailo(self, export_registry):
        # Rule 6/brief Phase 6: LLM export format must never be a vision
        # accelerator artifact -- GGUF/Ollama-compatible only.
        target = export_registry.get("local_llm")
        assert target is not None
        assert target.export_format == "gguf"

    def test_hospital_knowledge_rag_selects_sqlite_vector(self, export_registry):
        target = export_registry.get("hospital_knowledge_rag")
        assert target is not None
        assert target.export_format == "sqlite_vector"

    def test_tts_selects_wav_cache(self, export_registry):
        target = export_registry.get("tts")
        assert target is not None
        assert target.export_format == "wav_cache"

    def test_unknown_export_format_is_flagged_by_validate(self):
        from bonbon_data_pipeline.export_for_edge import ExportTarget

        registry = ExportTargetRegistry({
            "bad": ExportTarget(
                capability="bad", export_format="not_a_real_format",
                hardware_target="pi_cpu", fallback_export_format=None,
            )
        })
        assert any("unknown export_format" in p for p in registry.validate())


class TestRequiredBehavior9RollbackModelRemainsAvailable:
    def test_first_promotion_has_no_fallback(self, tracker):
        record = tracker.set_active("object_detection", "yolov8n_v1", "1.0.0")
        assert record.rollback_available is False

    def test_second_promotion_automatically_gets_previous_as_fallback(self, tracker):
        tracker.set_active("object_detection", "yolov8n_v1", "1.0.0")
        record = tracker.set_active("object_detection", "yolov8n_v2", "2.0.0")
        assert record.rollback_available is True
        assert record.fallback_model_id == "yolov8n_v1"
        assert record.fallback_model_version == "1.0.0"

    def test_rollback_restores_the_previous_model_as_active(self, tracker):
        tracker.set_active("object_detection", "yolov8n_v1", "1.0.0")
        tracker.set_active("object_detection", "yolov8n_v2", "2.0.0")
        rolled_back = tracker.rollback("object_detection")
        assert rolled_back.active_model_id == "yolov8n_v1"
        assert rolled_back.active_model_version == "1.0.0"
        # The rolled-back-FROM model becomes the new fallback -- rollback
        # is reversible too, not a one-way trapdoor.
        assert rolled_back.fallback_model_id == "yolov8n_v2"

    def test_rollback_without_any_fallback_raises_rather_than_silently_noop(self, tracker):
        tracker.set_active("object_detection", "yolov8n_v1", "1.0.0")
        with pytest.raises(RollbackUnavailableError):
            tracker.rollback("object_detection")

    def test_rollback_for_unknown_capability_raises(self, tracker):
        with pytest.raises(RollbackUnavailableError):
            tracker.rollback("never_deployed_capability")

    def test_deployment_state_persists_across_tracker_instances(self, tmp_path):
        path = tmp_path / "edge_deployments.json"
        EdgeDeploymentTracker(path).set_active("gesture_recognition", "g1", "1.0.0")
        reloaded = EdgeDeploymentTracker(path).get("gesture_recognition")
        assert reloaded is not None
        assert reloaded.active_model_id == "g1"

    def test_explicit_fallback_overrides_the_automatic_previous_active(self, tracker):
        tracker.set_active("tts", "piper_v1", "1.0.0")
        record = tracker.set_active("tts", "piper_v2", "2.0.0", fallback_model_id="piper_v0_manual", fallback_model_version="0.9.0")
        assert record.fallback_model_id == "piper_v0_manual"
