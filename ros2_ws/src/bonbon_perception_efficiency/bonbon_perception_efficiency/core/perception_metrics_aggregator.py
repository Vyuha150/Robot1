"""PerceptionMetricsAggregator — combines per-module ModuleHealth samples
(already published by every perception node — bonbon_vision, bonbon_gesture,
bonbon_multi_person_tracker, etc.) with the latest PerceptionBudget into one
consolidated snapshot for /bonbon/perception_efficiency/metrics.

Does not sample anything itself — every perception node already publishes
ModuleHealth at its own rate; this just aggregates what already exists
rather than adding a second metrics-collection pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

# Mirrors bonbon_msgs/ModuleHealth.msg status constants.
_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_WORST_FIRST = (_HEALTH_STALE, _HEALTH_ERROR, _HEALTH_WARN, _HEALTH_OK)


@dataclass
class ModuleMetricSample:
    module_name: str
    status: int
    latency_ms: float
    error_count: int
    processed_count: int


@dataclass
class MetricsSnapshot:
    module_count: int
    worst_status: int
    worst_status_module: str
    avg_latency_ms: float
    max_latency_ms: float
    total_errors: int
    total_processed: int


class PerceptionMetricsAggregator:
    def __init__(self) -> None:
        self._latest: dict[str, ModuleMetricSample] = {}

    def record(self, sample: ModuleMetricSample) -> None:
        self._latest[sample.module_name] = sample

    def forget(self, module_name: str) -> None:
        self._latest.pop(module_name, None)

    def snapshot(self) -> MetricsSnapshot:
        samples = list(self._latest.values())
        if not samples:
            return MetricsSnapshot(0, _HEALTH_OK, "", 0.0, 0.0, 0, 0)

        worst_status = _HEALTH_OK
        worst_module = ""
        for rank in _WORST_FIRST:
            match = next((s for s in samples if s.status == rank), None)
            if match is not None:
                worst_status, worst_module = rank, match.module_name
                break

        latencies = [s.latency_ms for s in samples]
        return MetricsSnapshot(
            module_count=len(samples),
            worst_status=worst_status,
            worst_status_module=worst_module,
            avg_latency_ms=sum(latencies) / len(latencies),
            max_latency_ms=max(latencies),
            total_errors=sum(s.error_count for s in samples),
            total_processed=sum(s.processed_count for s in samples),
        )
