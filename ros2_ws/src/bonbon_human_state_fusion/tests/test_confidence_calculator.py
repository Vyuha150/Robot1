"""Tests for compute_confidence — verifies it is NOT a plain average."""

from __future__ import annotations

from bonbon_human_state_fusion.core.confidence_calculator import (
    ConfidenceInputs,
    compute_confidence,
)


class TestNotAPlainAverage:
    def test_one_modality_scores_lower_than_four_at_same_average(self):
        one = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=0.9,
                emotion_confidence=None,
                gesture_confidence=None,
                speech_confidence=None,
            )
        )
        four = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=0.9,
                emotion_confidence=0.9,
                gesture_confidence=0.9,
                speech_confidence=0.9,
            )
        )
        # Same raw average (0.9) in both cases, but coverage differs.
        assert four > one

    def test_full_coverage_approaches_the_raw_average(self):
        result = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=0.8,
                emotion_confidence=0.8,
                gesture_confidence=0.8,
                speech_confidence=0.8,
            )
        )
        assert abs(result - 0.8) < 1e-6

    def test_minimum_coverage_floor(self):
        # avg=1.0, coverage=1/4=0.25 -> 1.0 * (0.5 + 0.5*0.25) = 0.625
        result = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=1.0,
                emotion_confidence=None,
                gesture_confidence=None,
                speech_confidence=None,
            )
        )
        assert abs(result - 0.625) < 1e-6
        assert result >= 0.5  # the documented floor: avg * 0.5 at minimum


class TestPartialCoverage:
    def test_two_of_four_modalities(self):
        result = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=1.0,
                emotion_confidence=1.0,
                gesture_confidence=None,
                speech_confidence=None,
            )
        )
        assert 0.0 < result < 1.0

    def test_lifecycle_always_counted(self):
        result = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=0.0,
                emotion_confidence=None,
                gesture_confidence=None,
                speech_confidence=None,
            )
        )
        assert result == 0.0


class TestBounds:
    def test_result_never_exceeds_one(self):
        result = compute_confidence(
            ConfidenceInputs(
                lifecycle_confidence=1.0,
                emotion_confidence=1.0,
                gesture_confidence=1.0,
                speech_confidence=1.0,
            )
        )
        assert result <= 1.0
