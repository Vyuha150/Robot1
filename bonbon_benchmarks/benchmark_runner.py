"""Top-level orchestrator: runs one, several, or all benchmark categories
and returns a combined report. Each category module owns its own
real-vs-BLOCKED decision -- this module never overrides a category's
result, only aggregates them.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import BenchmarkCategoryReport

CATEGORY_NAMES = (
    "resource",
    "ros2_latency",
    "speech_ai",
    "vision",
    "llm",
    "cache_efficiency",
    "safety_under_load",
    "dashboard",
    "three_pi_network",
)


def _run_resource() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.metrics_collector import BenchmarkMetric
    from bonbon_benchmarks.resource_monitor import FullResourceMonitor

    report = BenchmarkCategoryReport(category="resource")
    monitor = FullResourceMonitor()
    snap = monitor.sample()

    if not snap.available:
        blocked_reason = "psutil not installed in this environment"
        report.add(BenchmarkMetric.blocked(
            metric_name="cpu_percent", board="dev_sandbox", module="resource",
            scenario="instantaneous sample", reason=blocked_reason, unit="%",
        ))
        report.add(BenchmarkMetric.blocked(
            metric_name="memory_percent", board="dev_sandbox", module="resource",
            scenario="instantaneous sample", reason=blocked_reason, unit="%",
        ))
    else:
        cpu_metric = BenchmarkMetric(
            metric_name="cpu_percent", board="dev_sandbox", module="resource", scenario="instantaneous sample",
            avg=snap.cpu_percent, p50=snap.cpu_percent, p90=snap.cpu_percent, p95=snap.cpu_percent,
            p99=snap.cpu_percent, max=snap.cpu_percent, sample_count=1, unit="%", target=80.0, target_stat="avg",
        )
        cpu_metric.evaluate()
        report.add(cpu_metric)
        report.add(BenchmarkMetric(
            metric_name="memory_percent", board="dev_sandbox", module="resource", scenario="instantaneous sample",
            avg=snap.memory_percent, p50=snap.memory_percent, p90=snap.memory_percent, p95=snap.memory_percent,
            p99=snap.memory_percent, max=snap.memory_percent, sample_count=1, unit="%",
        ))
    if snap.temperature_c is None:
        report.add(BenchmarkMetric.blocked(
            metric_name="cpu_temperature", board="dev_sandbox", module="resource", scenario="thermal_zone sysfs read",
            reason="no /sys/class/thermal/thermal_zoneN/temp on this platform (not a real Pi)", unit="C",
        ))
    else:
        report.add(BenchmarkMetric(
            metric_name="cpu_temperature", board="dev_sandbox", module="resource", scenario="thermal_zone sysfs read",
            avg=snap.temperature_c, p50=snap.temperature_c, p90=snap.temperature_c, p95=snap.temperature_c,
            p99=snap.temperature_c, max=snap.temperature_c, sample_count=1, unit="C", target=80.0, target_stat="avg",
        ))
    return report


def _run_ros2_latency() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.ros2_latency_probe import run

    report = BenchmarkCategoryReport(category="ros2_latency")
    report.add(run())
    return report


def _run_speech_ai() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.speech_benchmark import run_all

    return run_all()


def _run_vision() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.vision_benchmark import run_all

    return run_all()


def _run_llm() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.llm_benchmark import benchmark_short_answer

    report = BenchmarkCategoryReport(category="llm")
    report.add(benchmark_short_answer())
    return report


def _run_cache_efficiency() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.rag_cache_benchmark import run_all

    return run_all()


def _run_safety_under_load() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.safety_latency_benchmark import run_all

    return run_all()


def _run_dashboard() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.dashboard_benchmark import run_all

    return run_all()


def _run_three_pi_network() -> BenchmarkCategoryReport:
    from bonbon_benchmarks.three_pi_network_benchmark import run_all

    return run_all()


_RUNNERS = {
    "resource": _run_resource,
    "ros2_latency": _run_ros2_latency,
    "speech_ai": _run_speech_ai,
    "vision": _run_vision,
    "llm": _run_llm,
    "cache_efficiency": _run_cache_efficiency,
    "safety_under_load": _run_safety_under_load,
    "dashboard": _run_dashboard,
    "three_pi_network": _run_three_pi_network,
}


@dataclass
class FullBenchmarkRun:
    generated_at: str
    hostname: str
    platform_str: str
    categories: list[BenchmarkCategoryReport] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def summary(self) -> dict[str, int]:
        counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
        for cat in self.categories:
            for status, n in cat.summary().items():
                counts[status] += n
        return counts

    def to_dict(self) -> dict:
        return {
            "generatedAt": self.generated_at,
            "hostname": self.hostname,
            "platform": self.platform_str,
            "elapsedSec": round(self.elapsed_sec, 2),
            "summary": self.summary(),
            "categories": [c.to_dict() for c in self.categories],
        }


def run(categories: list[str] | None = None) -> FullBenchmarkRun:
    selected = categories or list(CATEGORY_NAMES)
    unknown = [c for c in selected if c not in _RUNNERS]
    if unknown:
        raise ValueError(f"unknown benchmark categories: {unknown}; valid: {list(_RUNNERS)}")

    started = time.time()
    reports = [_RUNNERS[name]() for name in selected]
    elapsed = time.time() - started

    return FullBenchmarkRun(
        generated_at=datetime.now(timezone.utc).isoformat(),
        hostname=platform.node(),
        platform_str=platform.platform(),
        categories=reports,
        elapsed_sec=elapsed,
    )
