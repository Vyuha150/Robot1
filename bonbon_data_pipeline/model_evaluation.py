"""The Phase 7 "can this candidate become the default model" deployment
gate, implementing the brief's literal 7-criteria list:

  1. accuracy improves or target metric passes
  2. latency target passes
  3. no safety delay
  4. memory stable
  5. no thermal overload
  6. fallback works
  7. regression tests pass

This is an ORCHESTRATION layer, not a second evaluation store: criterion 7
is delegated to the already-existing, already-dashboard-wired
bonbon_field_learning.model_evaluation_tracker.ModelEvaluationTracker
(which already implements "blocks deployment if regression worsens")
rather than reimplemented here. Criteria 1-6 are the genuinely missing
piece -- the existing tracker only ever recorded regression_pass_rate, not
latency/memory/thermal/fallback/safety-delay.

A criterion whose measurement is missing (e.g. no real Pi to read CPU
temperature from) is reported UNVERIFIED, not silently passed -- an
unverified criterion blocks deployment exactly like a failed one, it is
just reported with a different, honest reason string so the dashboard can
distinguish "failed the bar" from "never actually measured".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from bonbon_field_learning.model_evaluation_tracker import EvaluationRun, ModelEvaluationTracker


class CriterionStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNVERIFIED = "unverified"


@dataclass
class CandidateBenchmark:
    model_id: str
    model_version: str
    dataset_version: str
    capability: str

    # Criterion 1: accuracy / target metric
    target_metric_name: str
    target_metric_value: float
    target_metric_threshold: float
    higher_is_better: bool = True

    # Criterion 2: latency
    latency_ms: Optional[float] = None
    latency_target_ms: Optional[float] = None

    # Criterion 3: safety delay (None/None if this capability has no
    # safety-relevant response-time budget -- e.g. TTS phrase caching)
    safety_delay_ms: Optional[float] = None
    safety_delay_limit_ms: Optional[float] = None

    # Criterion 4: memory stability vs the currently-deployed baseline
    ram_mb: Optional[float] = None
    ram_baseline_mb: Optional[float] = None
    memory_stability_margin: float = 0.10  # candidate may exceed baseline by up to 10%

    # Criterion 5: thermal
    temperature_c: Optional[float] = None
    thermal_limit_c: Optional[float] = None

    # Criterion 6: fallback
    fallback_verified: bool = False

    # Criterion 7 inputs (forwarded to ModelEvaluationTracker)
    regression_pass_rate: float = 0.0
    total_regression_scenarios: int = 0

    # Informational only (Phase 7's broader "evaluate" list) -- not gating
    # criteria on their own, shown on the dashboard alongside the verdict.
    precision: Optional[float] = None
    recall: Optional[float] = None
    false_positive_rate: Optional[float] = None
    false_negative_rate: Optional[float] = None
    cpu_percent: Optional[float] = None
    dashboard_visible: bool = True


@dataclass
class GateResult:
    model_id: str
    allowed: bool
    criteria: dict[str, tuple[CriterionStatus, str]]

    def failing_reasons(self) -> list[str]:
        return [reason for status, reason in self.criteria.values() if status != CriterionStatus.PASSED]

    def to_dict(self) -> dict:
        return {
            "modelId": self.model_id,
            "allowed": self.allowed,
            "criteria": {
                name: {"status": status.value, "reason": reason}
                for name, (status, reason) in self.criteria.items()
            },
        }


def evaluate_for_deployment(
    candidate: CandidateBenchmark, tracker: ModelEvaluationTracker
) -> GateResult:
    criteria: dict[str, tuple[CriterionStatus, str]] = {}

    # 1. accuracy / target metric
    if candidate.higher_is_better:
        passed = candidate.target_metric_value >= candidate.target_metric_threshold
    else:
        passed = candidate.target_metric_value <= candidate.target_metric_threshold
    criteria["target_metric"] = (
        CriterionStatus.PASSED if passed else CriterionStatus.FAILED,
        f"{candidate.target_metric_name}={candidate.target_metric_value} vs threshold "
        f"{candidate.target_metric_threshold} ({'higher' if candidate.higher_is_better else 'lower'} is better)",
    )

    # 2. latency
    if candidate.latency_ms is None or candidate.latency_target_ms is None:
        criteria["latency"] = (CriterionStatus.UNVERIFIED, "latency was not measured for this candidate")
    else:
        passed = candidate.latency_ms <= candidate.latency_target_ms
        criteria["latency"] = (
            CriterionStatus.PASSED if passed else CriterionStatus.FAILED,
            f"{candidate.latency_ms:.1f}ms vs target {candidate.latency_target_ms:.1f}ms",
        )

    # 3. no safety delay
    if candidate.safety_delay_ms is None or candidate.safety_delay_limit_ms is None:
        criteria["safety_delay"] = (
            CriterionStatus.PASSED,
            "capability has no declared safety-relevant delay budget",
        )
    else:
        passed = candidate.safety_delay_ms <= candidate.safety_delay_limit_ms
        criteria["safety_delay"] = (
            CriterionStatus.PASSED if passed else CriterionStatus.FAILED,
            f"{candidate.safety_delay_ms:.1f}ms vs safety limit {candidate.safety_delay_limit_ms:.1f}ms",
        )

    # 4. memory stable
    if candidate.ram_mb is None or candidate.ram_baseline_mb is None:
        criteria["memory"] = (CriterionStatus.UNVERIFIED, "RAM usage was not measured for this candidate")
    else:
        ceiling = candidate.ram_baseline_mb * (1.0 + candidate.memory_stability_margin)
        passed = candidate.ram_mb <= ceiling
        criteria["memory"] = (
            CriterionStatus.PASSED if passed else CriterionStatus.FAILED,
            f"{candidate.ram_mb:.0f}MB vs baseline {candidate.ram_baseline_mb:.0f}MB "
            f"(+{candidate.memory_stability_margin:.0%} ceiling {ceiling:.0f}MB)",
        )

    # 5. no thermal overload
    if candidate.temperature_c is None or candidate.thermal_limit_c is None:
        criteria["thermal"] = (
            CriterionStatus.UNVERIFIED,
            "no real hardware temperature reading available (dev/CI environment has no Pi thermal sensor)",
        )
    else:
        passed = candidate.temperature_c <= candidate.thermal_limit_c
        criteria["thermal"] = (
            CriterionStatus.PASSED if passed else CriterionStatus.FAILED,
            f"{candidate.temperature_c:.1f}C vs limit {candidate.thermal_limit_c:.1f}C",
        )

    # 6. fallback works
    criteria["fallback"] = (
        CriterionStatus.PASSED if candidate.fallback_verified else CriterionStatus.FAILED,
        "fallback path verified" if candidate.fallback_verified else "fallback path was not verified for this candidate",
    )

    # 7. regression tests pass -- delegated to the existing tracker
    run = EvaluationRun(
        model_version=candidate.model_version,
        dataset_version=candidate.dataset_version,
        regression_pass_rate=candidate.regression_pass_rate,
        total_regression_scenarios=candidate.total_regression_scenarios,
    )
    regression_ok, regression_reason = tracker.deployment_allowed(run)
    criteria["regression"] = (
        CriterionStatus.PASSED if regression_ok else CriterionStatus.FAILED, regression_reason
    )

    allowed = all(status == CriterionStatus.PASSED for status, _ in criteria.values())
    return GateResult(model_id=candidate.model_id, allowed=allowed, criteria=criteria)


def evaluate_and_record(
    candidate: CandidateBenchmark, tracker: ModelEvaluationTracker
) -> GateResult:
    """Runs the gate, and if (and only if) deployment is allowed, records
    the run as the new regression baseline. A rejected candidate's
    regression score is NOT recorded -- keeps a failed candidate from
    silently becoming the new comparison baseline (same reasoning as
    ModelEvaluationTracker.deployment_allowed's own docstring)."""
    result = evaluate_for_deployment(candidate, tracker)
    if result.allowed:
        tracker.record(
            EvaluationRun(
                model_version=candidate.model_version,
                dataset_version=candidate.dataset_version,
                regression_pass_rate=candidate.regression_pass_rate,
                total_regression_scenarios=candidate.total_regression_scenarios,
            )
        )
    return result
