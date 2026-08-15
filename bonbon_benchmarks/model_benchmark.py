"""Adds N-iteration percentile statistics on top of bonbon_ai_model_registry.
model_benchmark_runner's single-shot BenchmarkResult, for ASR/TTS/LLM
capabilities. Reuses that runner and scripts/ai_models/benchmark_all_models.py's
real invokers (Ollama HTTP, faster-whisper, Piper subprocess) rather than
inventing a second way to call these models -- this module's only job is
running the same real invoke N times and computing avg/p50/p90/p95/p99/max
over the results, which the single-shot runner doesn't do.

A capability where every iteration fails/blocks (e.g. no Ollama running,
no faster-whisper installed) reports BLOCKED with the real failure detail
from the last attempt -- never a fabricated latency number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import BenchmarkMetric, MetricSampler

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_AI_MODELS = _REPO_ROOT / "scripts" / "ai_models"
if str(_SCRIPTS_AI_MODELS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_AI_MODELS))


def _load_runner():
    """Lazy import -- benchmark_all_models.py loads the real
    config/models/model_registry.yaml at import time, which should only
    happen when a caller actually wants to benchmark, not on `import
    bonbon_benchmarks.model_benchmark`."""
    import benchmark_all_models as bam  # noqa: PLC0415
    from bonbon_ai_model_registry.model_benchmark_runner import BenchmarkRunner  # noqa: PLC0415
    from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor  # noqa: PLC0415
    from bonbon_ai_model_registry.model_registry import ModelRegistry  # noqa: PLC0415
    from bonbon_ai_model_registry.model_runtime_selector import (
        ModelRuntimeSelector,  # noqa: PLC0415
    )

    registry = ModelRegistry.load(bam.REGISTRY_PATH)
    selector = ModelRuntimeSelector(registry)
    health = ModelHealthMonitor(registry, selector)
    runner = BenchmarkRunner(registry, selector, health)
    return bam, runner


_INVOKER_ATTR = {"llm": "invoke_llm", "asr": "invoke_asr", "tts": "invoke_tts", "vision": "invoke_vision"}
_CASES_ATTR = {"llm": "LLM_CASES", "asr": "ASR_CASES", "tts": "TTS_CASES", "vision": "VISION_CASES"}


def benchmark_capability(
    category: str, *, iterations: int = 5, board: str = "dev_sandbox"
) -> BenchmarkMetric:
    """Runs `iterations` repeats of the FIRST case in benchmark_all_models.py's
    case list for `category` (llm/asr/tts/vision), through the real
    BenchmarkRunner + real invoker. Few iterations by default (models are
    slow); callers benchmarking a fast/mocked path can raise it."""
    bam, runner = _load_runner()
    cases = getattr(bam, _CASES_ATTR[category], [])
    invoke = getattr(bam, _INVOKER_ATTR[category])
    if not cases:
        return BenchmarkMetric.blocked(
            metric_name=f"{category}_model_latency", board=board, module=category,
            scenario="no case defined", reason=f"benchmark_all_models.py defines no cases for {category!r}",
        )
    case = cases[0]

    sampler = MetricSampler()
    last_detail = ""
    passes = 0
    for _ in range(iterations):
        result = runner.run_case(case, invoke)
        last_detail = result.detail
        if result.status == "pass" and result.latency_ms is not None:
            sampler.record(result.latency_ms)
            passes += 1

    if passes == 0:
        return BenchmarkMetric.blocked(
            metric_name=f"{category}_model_latency", board=board, module=category,
            scenario=f"{case.case_id} x{iterations}",
            reason=f"every iteration failed/blocked -- last detail: {last_detail}",
            recommendation="Verify the model runtime (Ollama/faster-whisper/Piper) is installed and running on this machine.",
        )

    return BenchmarkMetric.from_sampler(
        sampler, metric_name=f"{category}_model_latency", board=board, module=category,
        scenario=f"{case.case_id} x{iterations} ({passes}/{iterations} passed)", unit="ms",
        recommendation="" if passes == iterations else f"{iterations - passes}/{iterations} iterations failed -- see docs for detail.",
    )
