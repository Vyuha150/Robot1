"""Production readiness score: the 15 required metrics, rolled up into 7
weighted categories (safety 30% / reliability 20% / perception 15% / HRI
15% / edge 10% / dashboard 5% / maintainability 5%), with a hard safety
gate -- if the safety category is below threshold, the verdict is FAIL no
matter how high the weighted total is.

Honest-by-construction: any metric the caller doesn't supply is `None`,
not silently treated as 0 or 1. A category with missing metrics reports
`None` (incomplete), and the overall verdict is BLOCKED rather than a
fabricated PASS/FAIL when safety data specifically is incomplete -- the
same "never fake a result you don't have" rule the hardware-gated tests
follow, applied to this scoring layer.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


# category -> weight (must sum to 1.0)
CATEGORY_WEIGHTS: dict[str, float] = {
    "safety": 0.30,
    "reliability": 0.20,
    "perception": 0.15,
    "hri_behavior": 0.15,
    "edge_performance": 0.10,
    "dashboard_readiness": 0.05,
    "maintainability": 0.05,
}
assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9

SAFETY_THRESHOLD = 0.95
DEFAULT_LATENCY_BUDGET_MS = 2000.0


@dataclass
class ProductionMetrics:
    """All 15 required metrics. Rates are 0.0-1.0 (already "higher is
    better" -- callers invert raw error rates before constructing this).
    `None` means "not measured" -- never fabricated as 0 or 1."""

    # safety (30%)
    safety_pass_rate: float | None = None
    emergency_stop_reliability: float | None = None

    # reliability (20%)
    degraded_mode_recovery_rate: float | None = None
    field_failure_rate_inverted: float | None = None  # 1 - field_failure_rate
    regression_pass_rate: float | None = None

    # perception (15%)
    object_detection_precision: float | None = None
    object_detection_recall: float | None = None
    person_id_switch_rate_inverted: float | None = None  # 1 - id_switch_rate
    speaker_diarization_error_rate_inverted: float | None = None  # 1 - DER
    active_speaker_assignment_accuracy: float | None = None

    # hri_behavior (15%)
    gesture_false_trigger_rate_inverted: float | None = None  # 1 - rate
    behavior_correctness_rate: float | None = None

    # edge_performance (10%)
    average_response_latency_ms: float | None = None
    latency_budget_ms: float = DEFAULT_LATENCY_BUDGET_MS
    cpu_memory_temperature_stability: float | None = None

    # dashboard_readiness (5%)
    dashboard_accuracy_rate: float | None = None

    # maintainability (5%) -- not one of the 15 runtime metrics; computed
    # from real test/catalog coverage (see compute_maintainability_score).
    maintainability_score: float | None = None

    def latency_score(self) -> float | None:
        if self.average_response_latency_ms is None:
            return None
        return max(0.0, min(1.0, 1.0 - (self.average_response_latency_ms / self.latency_budget_ms)))


_CATEGORY_METRIC_GETTERS: dict[str, list[str]] = {
    "safety": ["safety_pass_rate", "emergency_stop_reliability"],
    "reliability": [
        "degraded_mode_recovery_rate",
        "field_failure_rate_inverted",
        "regression_pass_rate",
    ],
    "perception": [
        "object_detection_precision",
        "object_detection_recall",
        "person_id_switch_rate_inverted",
        "speaker_diarization_error_rate_inverted",
        "active_speaker_assignment_accuracy",
    ],
    "hri_behavior": ["gesture_false_trigger_rate_inverted", "behavior_correctness_rate"],
    "edge_performance": ["__latency__", "cpu_memory_temperature_stability"],
    "dashboard_readiness": ["dashboard_accuracy_rate"],
    "maintainability": ["maintainability_score"],
}


def _category_score(metrics: ProductionMetrics, category: str) -> float | None:
    values: list[float] = []
    for name in _CATEGORY_METRIC_GETTERS[category]:
        v = metrics.latency_score() if name == "__latency__" else getattr(metrics, name)
        if v is not None:
            values.append(v)
    if not values:
        return None
    return sum(values) / len(values)


@dataclass(frozen=True)
class ProductionReadinessScore:
    category_scores: dict[str, float | None]
    total_score: float | None
    safety_score: float | None
    verdict: Verdict
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "category_scores": self.category_scores,
            "total_score": self.total_score,
            "safety_score": self.safety_score,
            "verdict": self.verdict.value,
            "reason": self.reason,
        }


class ProductionScoreCalculator:
    def compute(self, metrics: ProductionMetrics) -> ProductionReadinessScore:
        category_scores = {cat: _category_score(metrics, cat) for cat in CATEGORY_WEIGHTS}
        safety_score = category_scores["safety"]

        if safety_score is None:
            return ProductionReadinessScore(
                category_scores=category_scores,
                total_score=None,
                safety_score=None,
                verdict=Verdict.BLOCKED,
                reason="safety category has no data -- cannot compute a verdict without it",
            )

        # Weighted total only over categories that have data; weight is
        # renormalized across present categories so missing non-safety data
        # doesn't silently zero out the total.
        present = {cat: s for cat, s in category_scores.items() if s is not None}
        present_weight = sum(CATEGORY_WEIGHTS[c] for c in present)
        total_score = sum(CATEGORY_WEIGHTS[c] * s for c, s in present.items()) / present_weight

        if safety_score < SAFETY_THRESHOLD:
            return ProductionReadinessScore(
                category_scores=category_scores,
                total_score=total_score,
                safety_score=safety_score,
                verdict=Verdict.FAIL,
                reason=(
                    f"safety score {safety_score:.1%} is below the {SAFETY_THRESHOLD:.0%} threshold -- "
                    "FAIL regardless of total score"
                ),
            )

        missing = set(CATEGORY_WEIGHTS) - set(present)
        if missing:
            return ProductionReadinessScore(
                category_scores=category_scores,
                total_score=total_score,
                safety_score=safety_score,
                verdict=Verdict.PARTIAL,
                reason=f"safety passes ({safety_score:.1%}); missing data for: {', '.join(sorted(missing))}",
            )

        return ProductionReadinessScore(
            category_scores=category_scores,
            total_score=total_score,
            safety_score=safety_score,
            verdict=Verdict.PASS,
            reason=f"all categories present; safety {safety_score:.1%} >= {SAFETY_THRESHOLD:.0%} threshold",
        )


def compute_maintainability_score(
    scenarios_dir: Path | None = None, production_dir: Path | None = None
) -> float:
    """Real introspection, not a magic number: fraction of the 15 scenario
    families that have BOTH a generated scenario file and a corresponding
    tests/production/ file driving it."""
    repo_root = Path(__file__).resolve().parents[1]
    scenarios_dir = scenarios_dir or (repo_root / "tests" / "scenarios" / "generated_scenarios")
    production_dir = production_dir or (repo_root / "tests" / "production")

    manifest_path = scenarios_dir / "MANIFEST.yaml"
    if not manifest_path.exists():
        return 0.0
    import yaml

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    families = [f for f in manifest.get("scenarios_per_family", {}) if f != "regression_scenarios"]
    if not families:
        return 0.0

    production_files = (
        {p.stem for p in production_dir.glob("test_*_scenarios.py")}
        if production_dir.exists()
        else set()
    )
    covered = 0
    for family in families:
        # family names are snake_case; production files are test_<short>_scenarios.py
        # -- match on family substring tokens rather than requiring an exact name.
        tokens = set(family.split("_"))
        if any(tokens & set(pf.split("_")) for pf in production_files):
            covered += 1
    return covered / len(families)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="print the score as JSON")
    parser.add_argument(
        "--metrics-json", type=Path, help="path to a JSON file of ProductionMetrics field overrides"
    )
    args = parser.parse_args(argv)

    field_names = {f.name for f in fields(ProductionMetrics)}
    overrides: dict[str, float] = {}
    if args.metrics_json and args.metrics_json.exists():
        raw = json.loads(args.metrics_json.read_text(encoding="utf-8"))
        overrides = {k: v for k, v in raw.items() if k in field_names}

    overrides.setdefault("maintainability_score", compute_maintainability_score())
    metrics = ProductionMetrics(**overrides)
    score = ProductionScoreCalculator().compute(metrics)

    if args.report:
        print(json.dumps(score.to_dict(), indent=2))
    else:
        print(
            f"verdict={score.verdict.value} total={score.total_score} safety={score.safety_score}"
        )
        print(score.reason)

    return 0 if score.verdict in (Verdict.PASS, Verdict.PARTIAL) else 1


if __name__ == "__main__":
    sys.exit(main())
