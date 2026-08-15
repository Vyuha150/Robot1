"""Safety-latency-under-load benchmarking (Phase 10) -- confirmed absent
anywhere in the repo before this (tests/edge_ai/test_safety_separation_guard.py
times `classify()` once, synchronously, with no concurrent load injected).

Times `SafetySeparationGuard.classify()` -- the real, centralized
safety-classification decision every proposed action passes through --
both at baseline and while a background thread injects simulated AI load
(busy-CPU spin + concurrent task-routing/cache calls), and compares the
delta against the canonical `safety_validation` budget (50ms p95,
critical) from `bonbon_safety.core.perf_targets`.

This benchmarks the CLASSIFICATION DECISION layer's stability under load,
not the physical emergency-stop reaction time (motor cutoff), which
requires real Safety Supervisor + e-stop hardware and is honestly
HARDWARE_BLOCKED in this environment -- both are reported, clearly
labeled, never conflated.
"""

from __future__ import annotations

import threading
import time

from bonbon_safety.core.perf_targets import build_targets

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import (
    BenchmarkCategoryReport,
    BenchmarkMetric,
    MetricSampler,
)


def _busy_spin_worker(stop_event: threading.Event) -> None:
    """Simulated AI load: continuous CPU-bound work (matches how a real
    LLM/ASR/vision inference loop would keep a core busy), not a sleep."""
    x = 0
    while not stop_event.is_set():
        for _ in range(20000):
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        time.sleep(0.0)  # yield


def _cache_load_worker(stop_event: threading.Event) -> None:
    from bonbon_edge_ai_runtime.cache_manager import CacheManager
    from bonbon_edge_ai_runtime.task_router import TaskRouter

    cache = CacheManager()
    router = TaskRouter()
    i = 0
    while not stop_event.is_set():
        cache.rag_get(f"q-{i}", "faq")
        router.route_text_intent("Where is cardiology?")
        i += 1


def benchmark_safety_classification(
    iterations: int = 300, concurrent_load: bool = False, board: str = "dev_sandbox"
) -> BenchmarkMetric:
    from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

    guard = SafetySeparationGuard()
    sampler = MetricSampler()

    stop_event = threading.Event()
    threads: list[threading.Thread] = []
    if concurrent_load:
        threads = [
            threading.Thread(target=_busy_spin_worker, args=(stop_event,), daemon=True),
            threading.Thread(target=_busy_spin_worker, args=(stop_event,), daemon=True),
            threading.Thread(target=_cache_load_worker, args=(stop_event,), daemon=True),
        ]
        for t in threads:
            t.start()

    try:
        for _ in range(iterations):
            started = time.perf_counter()
            guard.classify("llm", "text_response", {"text": "the cafeteria is on floor 1"})
            sampler.record((time.perf_counter() - started) * 1000.0)
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)

    budget = build_targets()["safety_validation"]
    scenario = (
        f"classify() x{iterations} under simulated concurrent AI load (2 CPU-spin + 1 cache/router thread)"
        if concurrent_load
        else f"classify() x{iterations}, no concurrent load (baseline)"
    )
    metric_name = "safety_classification_under_load" if concurrent_load else "safety_classification_baseline"
    return BenchmarkMetric.from_sampler(
        sampler, metric_name=metric_name, board=board, module="safety_separation", scenario=scenario,
        unit="ms", target=budget.budget_ms, target_stat=budget.metric,
        recommendation="critical budget -- AI load must never delay safety classification past this ceiling" if concurrent_load else "",
    )


def emergency_stop_reaction_hardware_blocked(board: str = "nav_pi") -> BenchmarkMetric:
    """Physical emergency-stop reaction (motor cutoff after e-stop signal)
    needs the real Safety Supervisor node + actual motor/e-stop hardware --
    neither exists in this environment. Never approximated with a mock."""
    budget = build_targets()["emergency_stop_reaction"]
    return BenchmarkMetric.blocked(
        metric_name="emergency_stop_reaction", board=board, module="safety_supervisor",
        scenario="e-stop signal to motor cutoff",
        reason="requires real Safety Supervisor node + motor/e-stop hardware, no ROS2/rclpy in this environment",
        recommendation=f"Must be measured on real Pi-3 + motor hardware against the {budget.budget_ms:.0f}ms {budget.metric} critical budget before production go-live.",
    )


def run_all(iterations: int = 300) -> BenchmarkCategoryReport:
    report = BenchmarkCategoryReport(category="safety_under_load")
    report.add(benchmark_safety_classification(iterations=iterations, concurrent_load=False))
    report.add(benchmark_safety_classification(iterations=iterations, concurrent_load=True))
    report.add(emergency_stop_reaction_hardware_blocked())
    return report
