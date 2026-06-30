"""Tests for TemporalSmoothingManager — generic label stability tracking."""

from __future__ import annotations

from bonbon_perception_efficiency.core.temporal_smoothing_manager import TemporalSmoothingManager


class TestSingleUpdate:
    def test_first_update_is_its_own_majority(self):
        mgr = TemporalSmoothingManager(window=5, min_agreement=0.6)
        result = mgr.update("ptrk_1", "happy")
        assert result.stable_label == "happy"
        assert result.is_stable is True
        assert result.agreement_fraction == 1.0


class TestStability:
    def test_consistent_labels_are_stable(self):
        mgr = TemporalSmoothingManager(window=4, min_agreement=0.6)
        for _ in range(4):
            result = mgr.update("ptrk_1", "neutral")
        assert result.is_stable is True
        assert result.agreement_fraction == 1.0

    def test_flickering_labels_are_unstable(self):
        mgr = TemporalSmoothingManager(window=4, min_agreement=0.75)
        labels = ["happy", "sad", "happy", "angry"]
        result = None
        for label in labels:
            result = mgr.update("ptrk_1", label)
        # 2/4 happy = 0.5 agreement, below the 0.75 threshold.
        assert result.is_stable is False

    def test_window_only_considers_recent_history(self):
        mgr = TemporalSmoothingManager(window=3, min_agreement=0.6)
        mgr.update("ptrk_1", "sad")
        mgr.update("ptrk_1", "sad")
        mgr.update("ptrk_1", "sad")
        result = mgr.update("ptrk_1", "happy")
        result = mgr.update("ptrk_1", "happy")
        # Window=3, last 3 are [sad, happy, happy] -> happy wins 2/3.
        assert result.stable_label == "happy"


class TestMultipleKeys:
    def test_keys_are_independent(self):
        mgr = TemporalSmoothingManager(window=3, min_agreement=0.6)
        mgr.update("ptrk_a", "happy")
        mgr.update("ptrk_b", "angry")
        a = mgr.update("ptrk_a", "happy")
        b = mgr.update("ptrk_b", "angry")
        assert a.stable_label == "happy"
        assert b.stable_label == "angry"
        assert mgr.tracked_key_count == 2


class TestForget:
    def test_forget_removes_history(self):
        mgr = TemporalSmoothingManager(window=3, min_agreement=0.6)
        mgr.update("ptrk_1", "happy")
        mgr.forget("ptrk_1")
        assert mgr.tracked_key_count == 0
        # Fresh history after forget — single update is fully stable again.
        result = mgr.update("ptrk_1", "angry")
        assert result.agreement_fraction == 1.0
