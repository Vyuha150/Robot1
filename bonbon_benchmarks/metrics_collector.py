"""BenchmarkMetric -- the one standardized output shape every module in
this package produces (Phase 2's exact required field list): metric name,
board, module, scenario, avg/p50/p90/p95/p99/max, pass/fail, blocked
reason, recommendation.

Built on `bonbon_safety.core.perf_monitor.percentile()` rather than a new
percentile implementation -- that function is already the repo's single
reusable percentile primitive. `LatencyStats` itself is not reused
directly because it only has p50/p95/p99 (no p90, which this brief
requires); `MetricSampler` below calls `percentile()` directly for all
five statistics instead of extending that dataclass.

Handles both latency-style metrics (unit="ms", lower is better) and
throughput-style metrics (unit="fps"/"hz"/"%", higher is better) through
the same percentile machinery -- a benchmark just says which direction is
"good" via `higher_is_better`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bonbon_safety.core.perf_monitor import percentile

Status = Literal["PASS", "FAIL", "BLOCKED"]


class MetricSampler:
    """Collects raw samples for one metric and computes avg/p50/p90/p95/p99/max
    on demand. Deliberately simpler than LatencyTracker (no rolling window
    eviction) -- a benchmark run is bounded and finite, unlike a long-lived
    node's rolling window."""

    def __init__(self) -> None:
        self._samples: list[float] = []

    def record(self, value: float) -> None:
        self._samples.append(float(value))

    def extend(self, values: list[float]) -> None:
        self._samples.extend(float(v) for v in values)

    @property
    def samples(self) -> list[float]:
        return list(self._samples)

    @property
    def count(self) -> int:
        return len(self._samples)

    def summary(self) -> dict[str, float]:
        if not self._samples:
            return {"avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        return {
            "avg": sum(self._samples) / len(self._samples),
            "p50": percentile(self._samples, 50),
            "p90": percentile(self._samples, 90),
            "p95": percentile(self._samples, 95),
            "p99": percentile(self._samples, 99),
            "max": max(self._samples),
        }


@dataclass
class BenchmarkMetric:
    metric_name: str
    board: str
    module: str
    scenario: str
    avg: float
    p50: float
    p90: float
    p95: float
    p99: float
    max: float
    sample_count: int
    unit: str = "ms"
    higher_is_better: bool = False
    target: float | None = None
    target_stat: str = "p95"  # which of avg/p50/p90/p95/p99/max the target applies to
    status: Status = "PASS"
    blocked_reason: str = ""
    recommendation: str = ""

    @classmethod
    def from_sampler(
        cls,
        sampler: MetricSampler,
        *,
        metric_name: str,
        board: str,
        module: str,
        scenario: str,
        unit: str = "ms",
        higher_is_better: bool = False,
        target: float | None = None,
        target_stat: str = "p95",
        recommendation: str = "",
    ) -> "BenchmarkMetric":
        s = sampler.summary()
        metric = cls(
            metric_name=metric_name, board=board, module=module, scenario=scenario,
            avg=round(s["avg"], 3), p50=round(s["p50"], 3), p90=round(s["p90"], 3),
            p95=round(s["p95"], 3), p99=round(s["p99"], 3), max=round(s["max"], 3),
            sample_count=sampler.count, unit=unit, higher_is_better=higher_is_better,
            target=target, target_stat=target_stat, recommendation=recommendation,
        )
        metric.evaluate()
        return metric

    @classmethod
    def blocked(
        cls,
        *,
        metric_name: str,
        board: str,
        module: str,
        scenario: str,
        reason: str,
        unit: str = "ms",
        recommendation: str = "",
    ) -> "BenchmarkMetric":
        """Never PASS, never a fabricated number -- the required shape for
        every hardware-dependent metric this environment cannot measure."""
        return cls(
            metric_name=metric_name, board=board, module=module, scenario=scenario,
            avg=0.0, p50=0.0, p90=0.0, p95=0.0, p99=0.0, max=0.0, sample_count=0,
            unit=unit, status="BLOCKED", blocked_reason=reason,
            recommendation=recommendation or "Run on real target hardware before treating as production-representative.",
        )

    def evaluate(self) -> None:
        """Sets status from `target`/`target_stat`/`higher_is_better`. A
        BLOCKED metric (sample_count==0, no target measured) is never
        silently promoted to PASS/FAIL by this -- only call on a metric
        that actually has samples."""
        if self.sample_count == 0:
            return
        if self.target is None:
            self.status = "PASS"
            return
        observed = getattr(self, self.target_stat, self.p95)
        met = (observed >= self.target) if self.higher_is_better else (observed <= self.target)
        self.status = "PASS" if met else "FAIL"

    def to_dict(self) -> dict:
        return {
            "metricName": self.metric_name,
            "board": self.board,
            "module": self.module,
            "scenario": self.scenario,
            "avg": self.avg,
            "p50": self.p50,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
            "unit": self.unit,
            "sampleCount": self.sample_count,
            "higherIsBetter": self.higher_is_better,
            "target": self.target,
            "targetStat": self.target_stat,
            "status": self.status,
            "blockedReason": self.blocked_reason,
            "recommendation": self.recommendation,
        }


@dataclass
class BenchmarkCategoryReport:
    """One phase's/category's full set of metrics, e.g. all speech-AI
    metrics or all safety-under-load metrics."""

    category: str
    metrics: list[BenchmarkMetric] = field(default_factory=list)

    def add(self, metric: BenchmarkMetric) -> BenchmarkMetric:
        self.metrics.append(metric)
        return metric

    def summary(self) -> dict[str, int]:
        counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
        for m in self.metrics:
            counts[m.status] += 1
        return counts

    def to_dict(self) -> dict:
        return {"category": self.category, "summary": self.summary(), "metrics": [m.to_dict() for m in self.metrics]}
