"""Tests for ModelEvaluationStore — recorded evaluations + version comparison."""

from __future__ import annotations

from bonbon_data_feedback.core.feedback_store import FeedbackStore
from bonbon_data_feedback.core.model_evaluation_store import ModelEvaluationStore


def _store(tmp_path):
    fs = FeedbackStore(tmp_path / "feedback.db")
    return ModelEvaluationStore(fs)


class TestRecordAndList:
    def test_record_evaluation_returns_id(self, tmp_path):
        store = _store(tmp_path)
        eval_id = store.record_evaluation("gesture_classifier", "v1", "gesture", 100, 0.85)
        assert eval_id

    def test_list_evaluations_filters_by_model(self, tmp_path):
        store = _store(tmp_path)
        store.record_evaluation("gesture_classifier", "v1", "gesture", 100, 0.85)
        store.record_evaluation("object_classifier", "v1", "object", 100, 0.80)
        results = store.list_evaluations(model_name="gesture_classifier")
        assert len(results) == 1
        assert results[0]["category"] == "gesture"


class TestCompare:
    def test_compare_detects_improvement(self, tmp_path):
        store = _store(tmp_path)
        store.record_evaluation("gesture_classifier", "v1", "gesture", 100, 0.80)
        store.record_evaluation("gesture_classifier", "v2", "gesture", 100, 0.90)
        cmp = store.compare("gesture_classifier", "v1", "v2")
        assert cmp.improved is True
        assert cmp.accuracy_a == 0.80
        assert cmp.accuracy_b == 0.90

    def test_compare_detects_regression(self, tmp_path):
        store = _store(tmp_path)
        store.record_evaluation("gesture_classifier", "v1", "gesture", 100, 0.90)
        store.record_evaluation("gesture_classifier", "v2", "gesture", 100, 0.70)
        cmp = store.compare("gesture_classifier", "v1", "v2")
        assert cmp.improved is False

    def test_compare_missing_version_returns_none_improved(self, tmp_path):
        store = _store(tmp_path)
        store.record_evaluation("gesture_classifier", "v1", "gesture", 100, 0.90)
        cmp = store.compare("gesture_classifier", "v1", "v_missing")
        assert cmp.improved is None
        assert cmp.accuracy_b is None
