"""Unit tests for bonbon_behavior_validation.production_score: the
weighted rollup, the hard safety gate, and the honest-missing-data
handling (never fabricate a metric value)."""

from __future__ import annotations

from bonbon_behavior_validation import ProductionMetrics, ProductionScoreCalculator, Verdict
from bonbon_behavior_validation.production_score import (
    CATEGORY_WEIGHTS,
    SAFETY_THRESHOLD,
    compute_maintainability_score,
)


def _all_high_metrics(**overrides) -> ProductionMetrics:
    base = dict(
        safety_pass_rate=0.99,
        emergency_stop_reliability=0.98,
        degraded_mode_recovery_rate=0.95,
        field_failure_rate_inverted=0.9,
        regression_pass_rate=0.97,
        object_detection_precision=0.9,
        object_detection_recall=0.88,
        person_id_switch_rate_inverted=0.95,
        speaker_diarization_error_rate_inverted=0.9,
        active_speaker_assignment_accuracy=0.93,
        gesture_false_trigger_rate_inverted=0.96,
        behavior_correctness_rate=0.97,
        average_response_latency_ms=400.0,
        cpu_memory_temperature_stability=0.9,
        dashboard_accuracy_rate=0.99,
        maintainability_score=0.95,
    )
    base.update(overrides)
    return ProductionMetrics(**base)


class TestCategoryWeights:
    def test_weights_sum_to_one(self):
        assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9

    def test_safety_is_the_largest_weight(self):
        assert CATEGORY_WEIGHTS["safety"] == max(CATEGORY_WEIGHTS.values())
        assert CATEGORY_WEIGHTS["safety"] == 0.30


class TestSafetyGate:
    def test_high_safety_and_total_passes(self):
        score = ProductionScoreCalculator().compute(_all_high_metrics())
        assert score.verdict == Verdict.PASS
        assert score.safety_score >= SAFETY_THRESHOLD

    def test_low_safety_fails_even_with_perfect_everything_else(self):
        metrics = _all_high_metrics(safety_pass_rate=0.5, emergency_stop_reliability=0.5)
        score = ProductionScoreCalculator().compute(metrics)
        assert score.verdict == Verdict.FAIL
        assert score.safety_score < SAFETY_THRESHOLD
        assert "below" in score.reason

    def test_safety_just_below_threshold_fails(self):
        metrics = _all_high_metrics(safety_pass_rate=0.94, emergency_stop_reliability=0.94)
        score = ProductionScoreCalculator().compute(metrics)
        assert score.verdict == Verdict.FAIL

    def test_safety_at_exactly_threshold_passes(self):
        metrics = _all_high_metrics(
            safety_pass_rate=SAFETY_THRESHOLD, emergency_stop_reliability=SAFETY_THRESHOLD
        )
        score = ProductionScoreCalculator().compute(metrics)
        assert score.verdict in (Verdict.PASS, Verdict.PARTIAL)
        assert score.safety_score == SAFETY_THRESHOLD


class TestMissingDataIsNeverFabricated:
    def test_no_metrics_at_all_is_blocked_not_a_fake_score(self):
        score = ProductionScoreCalculator().compute(ProductionMetrics())
        assert score.verdict == Verdict.BLOCKED
        assert score.total_score is None
        assert score.safety_score is None

    def test_safety_present_but_others_missing_is_partial(self):
        metrics = ProductionMetrics(safety_pass_rate=0.99, emergency_stop_reliability=0.98)
        score = ProductionScoreCalculator().compute(metrics)
        assert score.verdict == Verdict.PARTIAL
        assert score.category_scores["perception"] is None
        assert score.category_scores["safety"] is not None

    def test_missing_safety_blocks_even_if_everything_else_is_perfect(self):
        metrics = _all_high_metrics(safety_pass_rate=None, emergency_stop_reliability=None)
        score = ProductionScoreCalculator().compute(metrics)
        assert score.verdict == Verdict.BLOCKED


class TestLatencyScoring:
    def test_latency_within_budget_scores_well(self):
        metrics = ProductionMetrics(average_response_latency_ms=200.0, latency_budget_ms=2000.0)
        assert metrics.latency_score() == 0.9

    def test_latency_over_budget_clamps_to_zero(self):
        metrics = ProductionMetrics(average_response_latency_ms=5000.0, latency_budget_ms=2000.0)
        assert metrics.latency_score() == 0.0

    def test_no_latency_measured_is_none(self):
        assert ProductionMetrics().latency_score() is None


class TestMaintainabilityScore:
    def test_real_repo_state_is_fully_covered(self):
        # Every Phase-2 family has a Phase-4 production test file by now.
        score = compute_maintainability_score()
        assert score == 1.0

    def test_missing_manifest_returns_zero(self, tmp_path):
        score = compute_maintainability_score(scenarios_dir=tmp_path, production_dir=tmp_path)
        assert score == 0.0
