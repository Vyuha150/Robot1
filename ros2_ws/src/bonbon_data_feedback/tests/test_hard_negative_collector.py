"""Tests for HardNegativeCollector — the confident-but-wrong subset."""

from __future__ import annotations

from bonbon_data_feedback.core.feedback_store import FeedbackStore
from bonbon_data_feedback.core.hard_negative_collector import HardNegativeCollector
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy


def _collector(tmp_path, threshold=0.7):
    store = FeedbackStore(tmp_path / "feedback.db")
    policy = PrivacySafeDataPolicy()
    return HardNegativeCollector(store, policy, confidence_threshold=threshold), store


class TestIsHardNegative:
    def test_confident_and_wrong_is_hard_negative(self, tmp_path):
        collector, _ = _collector(tmp_path, threshold=0.7)
        assert collector.is_hard_negative(confidence=0.9, was_correct=False) is True

    def test_confident_and_correct_is_not_hard_negative(self, tmp_path):
        collector, _ = _collector(tmp_path, threshold=0.7)
        assert collector.is_hard_negative(confidence=0.9, was_correct=True) is False

    def test_low_confidence_and_wrong_is_not_hard_negative(self, tmp_path):
        """An honest low-confidence miss is a normal failure case, not the
        confident-but-wrong pattern this collector exists to find."""
        collector, _ = _collector(tmp_path, threshold=0.7)
        assert collector.is_hard_negative(confidence=0.3, was_correct=False) is False

    def test_threshold_boundary_is_inclusive(self, tmp_path):
        collector, _ = _collector(tmp_path, threshold=0.7)
        assert collector.is_hard_negative(confidence=0.7, was_correct=False) is True


class TestCollect:
    def test_collect_persists_when_hard_negative(self, tmp_path):
        collector, store = _collector(tmp_path, threshold=0.7)
        case_id = collector.collect("gesture", "wave_detector", "wave", 0.95, was_correct=False)
        assert case_id is not None
        got = store.get_failure_case(case_id)
        assert got.is_hard_negative is True

    def test_collect_returns_none_when_not_hard_negative(self, tmp_path):
        collector, store = _collector(tmp_path, threshold=0.7)
        case_id = collector.collect("gesture", "wave_detector", "wave", 0.95, was_correct=True)
        assert case_id is None
        assert store.count_failure_cases() == 0

    def test_collect_does_not_persist_low_confidence_misses(self, tmp_path):
        collector, store = _collector(tmp_path, threshold=0.7)
        collector.collect("gesture", "wave_detector", "wave", 0.2, was_correct=False)
        assert store.count_failure_cases() == 0
