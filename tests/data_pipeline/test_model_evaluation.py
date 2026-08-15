"""Required test 7: a model cannot become the default without a benchmark.

Covers all 7 deployment-gate criteria from Phase 7, including the
UNVERIFIED-blocks-just-like-FAILED behavior for unmeasured criteria.
"""

from __future__ import annotations

import pytest

from bonbon_data_pipeline.model_evaluation import (
    CandidateBenchmark,
    CriterionStatus,
    evaluate_and_record,
    evaluate_for_deployment,
)
from bonbon_field_learning.model_evaluation_tracker import EvaluationRun, ModelEvaluationTracker


def _fully_passing_candidate(**overrides) -> CandidateBenchmark:
    defaults = dict(
        model_id="m1", model_version="1.0.0", dataset_version="0.1.0", capability="object_detection",
        target_metric_name="map_50_95", target_metric_value=0.6, target_metric_threshold=0.55,
        latency_ms=80.0, latency_target_ms=100.0,
        ram_mb=500.0, ram_baseline_mb=500.0,
        temperature_c=60.0, thermal_limit_c=75.0,
        fallback_verified=True,
        regression_pass_rate=1.0, total_regression_scenarios=10,
    )
    defaults.update(overrides)
    return CandidateBenchmark(**defaults)


@pytest.fixture
def tracker(tmp_path):
    return ModelEvaluationTracker(tmp_path / "model_evaluation.json")


class TestRequiredBehavior7NoDeploymentWithoutBenchmark:
    def test_no_measurements_at_all_blocks_deployment(self, tracker):
        candidate = _fully_passing_candidate(
            latency_ms=None, latency_target_ms=None,
            ram_mb=None, ram_baseline_mb=None,
            temperature_c=None, thermal_limit_c=None,
        )
        result = evaluate_for_deployment(candidate, tracker)
        assert result.allowed is False
        assert result.criteria["memory"][0] == CriterionStatus.UNVERIFIED
        assert result.criteria["thermal"][0] == CriterionStatus.UNVERIFIED

    def test_fully_passing_candidate_is_allowed(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(), tracker)
        assert result.allowed is True
        assert all(status == CriterionStatus.PASSED for status, _ in result.criteria.values())


class TestIndividualCriteria:
    def test_target_metric_below_threshold_blocks(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(target_metric_value=0.4), tracker)
        assert result.criteria["target_metric"][0] == CriterionStatus.FAILED
        assert result.allowed is False

    def test_latency_over_target_blocks(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(latency_ms=200.0), tracker)
        assert result.criteria["latency"][0] == CriterionStatus.FAILED

    def test_capability_with_no_safety_delay_budget_passes_that_criterion_automatically(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(), tracker)
        assert result.criteria["safety_delay"][0] == CriterionStatus.PASSED

    def test_safety_delay_over_limit_blocks(self, tracker):
        candidate = _fully_passing_candidate(safety_delay_ms=500.0, safety_delay_limit_ms=200.0)
        result = evaluate_for_deployment(candidate, tracker)
        assert result.criteria["safety_delay"][0] == CriterionStatus.FAILED

    def test_ram_more_than_10_percent_over_baseline_blocks(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(ram_mb=600.0, ram_baseline_mb=500.0), tracker)
        assert result.criteria["memory"][0] == CriterionStatus.FAILED

    def test_ram_within_10_percent_margin_passes(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(ram_mb=540.0, ram_baseline_mb=500.0), tracker)
        assert result.criteria["memory"][0] == CriterionStatus.PASSED

    def test_thermal_over_limit_blocks(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(temperature_c=90.0), tracker)
        assert result.criteria["thermal"][0] == CriterionStatus.FAILED

    def test_fallback_not_verified_blocks(self, tracker):
        result = evaluate_for_deployment(_fully_passing_candidate(fallback_verified=False), tracker)
        assert result.criteria["fallback"][0] == CriterionStatus.FAILED

    def test_regression_worse_than_previous_blocks(self, tracker):
        tracker.record(
            EvaluationRun(
                model_version="0.9.0", dataset_version="0.1.0",
                regression_pass_rate=0.95, total_regression_scenarios=10,
            )
        )
        result = evaluate_for_deployment(_fully_passing_candidate(regression_pass_rate=0.80), tracker)
        assert result.criteria["regression"][0] == CriterionStatus.FAILED
        assert result.allowed is False


class TestEvaluateAndRecord:
    def test_passing_candidate_is_recorded_as_new_baseline(self, tracker):
        result = evaluate_and_record(_fully_passing_candidate(), tracker)
        assert result.allowed is True
        assert tracker.latest() is not None
        assert tracker.latest().model_version == "1.0.0"

    def test_rejected_candidate_is_not_recorded(self, tracker):
        result = evaluate_and_record(_fully_passing_candidate(fallback_verified=False), tracker)
        assert result.allowed is False
        assert tracker.latest() is None
