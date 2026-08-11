#!/usr/bin/env python3
"""benchmark_edge_ai_stack.py -- Edge AI Runtime brief Phase 14.

Unlike scripts/ai_models/benchmark_all_models.py (which benchmarks real
model INFERENCE -- ASR/TTS/LLM/vision -- and is mostly BLOCKED on a dev
sandbox with no Ollama/camera/Hailo installed), this script benchmarks
the edge_ai RUNTIME LAYER itself: task_router, safety_separation_guard,
cache_manager, resource_guard, inference_scheduler, accelerator_manager.
These are pure-Python orchestration/decision code with no external
hardware dependency, so they genuinely execute and produce real timing
numbers on any machine -- there is no "BLOCKED, no Ollama here" case for
this layer, only real pass/fail against real code.

Each category below runs N iterations of a representative real call and
reports min/mean/p95/max latency in milliseconds -- never a fabricated
number. A category that raises is reported failed, not silently skipped.

Usage:
    python3 scripts/edge_ai/benchmark_edge_ai_stack.py
    python3 scripts/edge_ai/benchmark_edge_ai_stack.py --category task_routing
    python3 scripts/edge_ai/benchmark_edge_ai_stack.py --iterations 500
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "ros2_ws" / "src"
for _extra in (
    _SRC / "bonbon_edge_ai_runtime",
    _SRC / "bonbon_ai_model_registry",
    _SRC / "bonbon_ai_runtime",
    _SRC / "bonbon_perception_efficiency",
    _SRC / "bonbon_llm",
    _SRC / "bonbon_safety",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

RESULTS_PATH = _REPO_ROOT / "docs" / "project-status" / "edge_ai_benchmark_results.json"


@dataclass
class CategoryResult:
    category: str
    status: str  # "pass" | "fail"
    iterations: int
    min_ms: float | None = None
    mean_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "status": self.status,
            "iterations": self.iterations,
            "minMs": self.min_ms,
            "meanMs": self.mean_ms,
            "p95Ms": self.p95_ms,
            "maxMs": self.max_ms,
            "detail": self.detail,
        }


def _time_iterations(fn: Callable[[], None], iterations: int) -> list[float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


def _summarize(category: str, samples: list[float]) -> CategoryResult:
    samples_sorted = sorted(samples)
    p95_index = min(len(samples_sorted) - 1, int(len(samples_sorted) * 0.95))
    return CategoryResult(
        category=category,
        status="pass",
        iterations=len(samples),
        min_ms=samples_sorted[0],
        mean_ms=statistics.mean(samples),
        p95_ms=samples_sorted[p95_index],
        max_ms=samples_sorted[-1],
        detail="ok",
    )


def bench_task_routing(iterations: int) -> CategoryResult:
    import itertools

    from bonbon_edge_ai_runtime.task_router import TaskRouter

    router = TaskRouter()
    utterances = itertools.cycle([
        "help, someone collapsed",
        "Where is Cardiology?",
        "Book appointment with Dr. Rao",
        "Guide me to room 203",
        "what's your favorite color",
    ])
    try:
        samples = _time_iterations(lambda: router.route_text_intent(next(utterances)), iterations)
    except Exception as exc:  # noqa: BLE001 -- a benchmark failure must be recorded honestly
        return CategoryResult("task_routing", "fail", 0, detail=str(exc))
    return _summarize("task_routing", samples)


def bench_safety_separation(iterations: int) -> CategoryResult:
    from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

    guard = SafetySeparationGuard()
    try:
        samples = _time_iterations(lambda: guard.classify("llm", "text_response", {"text": "the cafeteria is on floor 1"}), iterations)
    except Exception as exc:  # noqa: BLE001
        return CategoryResult("safety_separation", "fail", 0, detail=str(exc))
    return _summarize("safety_separation", samples)


def bench_caching(iterations: int) -> CategoryResult:
    from bonbon_edge_ai_runtime.cache_manager import CacheManager

    cache = CacheManager()
    cache.rag_put("where is radiology", "faq", ["Radiology is on floor 2"])
    try:
        samples = _time_iterations(lambda: cache.rag_get("where is radiology", "faq"), iterations)
    except Exception as exc:  # noqa: BLE001
        return CategoryResult("caching", "fail", 0, detail=str(exc))
    return _summarize("caching", samples)


def bench_resource_guard(iterations: int) -> CategoryResult:
    from bonbon_edge_ai_runtime.resource_guard import ResourceGuard

    guard = ResourceGuard()
    try:
        samples = _time_iterations(lambda: guard.evaluate(temp_c=45.0, safety_state_name="SAFETY_NORMAL", safety_caution_or_above=False), iterations)
    except Exception as exc:  # noqa: BLE001
        return CategoryResult("resource_guard", "fail", 0, detail=str(exc))
    return _summarize("resource_guard", samples)


def bench_inference_scheduling(iterations: int) -> CategoryResult:
    from bonbon_edge_ai_runtime.inference_scheduler import InferenceScheduler

    scheduler = InferenceScheduler()
    try:
        samples = _time_iterations(lambda: scheduler.submit("ai_pi_speech", f"bench-{time.perf_counter_ns()}"), iterations)
    except Exception as exc:  # noqa: BLE001
        return CategoryResult("inference_scheduling", "fail", 0, detail=str(exc))
    return _summarize("inference_scheduling", samples)


def bench_accelerator_selection(iterations: int) -> CategoryResult:
    from bonbon_ai_runtime.runtime_selector import RuntimeMode, RuntimeSpec
    from bonbon_edge_ai_runtime.accelerator_manager import AcceleratorManager

    manager = AcceleratorManager()
    spec = RuntimeSpec(mode=RuntimeMode.MOCK)  # forced mock -- no real Hailo/OAK-D on this sandbox
    try:
        samples = _time_iterations(lambda: manager.select("object_detection", spec), iterations)
    except Exception as exc:  # noqa: BLE001
        return CategoryResult("accelerator_selection", "fail", 0, detail=str(exc))
    result = _summarize("accelerator_selection", samples)
    result.detail = "mock runtime forced -- no real Hailo/OAK-D hardware on this sandbox, see docs/EDGE_AI_BENCHMARK_REPORT.md"
    return result


ALL_CATEGORIES: dict[str, Callable[[int], CategoryResult]] = {
    "task_routing": bench_task_routing,
    "safety_separation": bench_safety_separation,
    "caching": bench_caching,
    "resource_guard": bench_resource_guard,
    "inference_scheduling": bench_inference_scheduling,
    "accelerator_selection": bench_accelerator_selection,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=list(ALL_CATEGORIES.keys()), default=None)
    parser.add_argument("--iterations", type=int, default=200)
    args = parser.parse_args()

    categories = [args.category] if args.category else list(ALL_CATEGORIES.keys())

    print(f"Running {len(categories)} edge_ai benchmark categor(y/ies), {args.iterations} iterations each...")  # noqa: T201
    started = time.time()
    results = [ALL_CATEGORIES[cat](args.iterations) for cat in categories]
    elapsed = time.time() - started

    print(f"\n{'CATEGORY':<24} {'STATUS':<8} {'MIN':<10} {'MEAN':<10} {'P95':<10} {'MAX':<10} DETAIL")  # noqa: T201
    print("-" * 110)  # noqa: T201
    for r in results:
        fmt = lambda v: f"{v:.3f}ms" if v is not None else "-"  # noqa: E731
        print(f"{r.category:<24} {r.status:<8} {fmt(r.min_ms):<10} {fmt(r.mean_ms):<10} {fmt(r.p95_ms):<10} {fmt(r.max_ms):<10} {r.detail[:50]}")  # noqa: T201

    passed = sum(1 for r in results if r.status == "pass")
    print(f"\nSummary: {passed}/{len(results)} categories passed in {elapsed:.2f}s")  # noqa: T201

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "note": (
                "Run on the dev sandbox, not real Pi-2/Pi-3 hardware. Unlike "
                "scripts/ai_models/benchmark_all_models.py, every category here "
                "is pure-Python orchestration code with no external hardware "
                "dependency, so these numbers are real end-to-end timings on "
                "this machine -- not blocked/fabricated. Real Pi ARM CPU timing "
                "must still be measured separately before treating these as "
                "production-representative (see docs/EDGE_AI_BENCHMARK_REPORT.md)."
            ),
        },
        "categories_run": categories,
        "iterations_per_category": args.iterations,
        "results": [r.to_dict() for r in results],
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nResults persisted to {RESULTS_PATH}")  # noqa: T201
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
