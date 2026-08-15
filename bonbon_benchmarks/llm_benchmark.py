"""Local LLM (Qwen2.5 0.5B) latency benchmarking. Reuses model_benchmark's
real Ollama-HTTP invoker -- no second way of calling the model.
"""

from __future__ import annotations

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import BenchmarkMetric
from bonbon_benchmarks.model_benchmark import benchmark_capability

# Phase 3 target: "Local LLM Qwen2.5 0.5B short answer: target 1-2 seconds".
# Using the upper bound as the pass/fail ceiling; the lower bound is
# reported for context in the recommendation, not enforced separately.
_TARGET_MS = 2000.0


def benchmark_short_answer(iterations: int = 3, board: str = "ai_pi") -> BenchmarkMetric:
    m = benchmark_capability("llm", iterations=iterations, board=board)
    m.target, m.target_stat = _TARGET_MS, "p95"
    m.recommendation = (
        m.recommendation
        + f" Target band is 1000-{_TARGET_MS:.0f}ms; only the {_TARGET_MS:.0f}ms ceiling is enforced as pass/fail."
    ).strip()
    m.evaluate()
    return m
