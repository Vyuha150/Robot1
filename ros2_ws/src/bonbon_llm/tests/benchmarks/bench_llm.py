"""
tests.benchmarks.bench_llm
============================
Latency benchmarks for the bonbon_llm pipeline components.

Measures p50 / p95 / p99 latencies against design budgets:

  Component               Budget (ms)
  ----------------------  -----------
  SafetyCommandFilter     < 1 ms
  HallucinationGuard      < 1 ms
  RAGRetriever (NumPy)    < 50 ms
  PersonalityLayer.apply  < 2 ms
  ToolRegistry.dispatch   < 5 ms  (read-only tools)
  Full pipeline (no LLM)  < 75 ms

Run with:
  python -m tests.benchmarks.bench_llm
or via pytest:
  pytest tests/benchmarks/bench_llm.py -v -s

Results are printed to stdout only (no assertions by default).
Set STRICT=1 env var to turn budget violations into assertion errors.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import types
from collections.abc import Callable

# ── Stub ROS2 for standalone execution ────────────────────────────────────────


def _stub():
    for name in (
        "rclpy",
        "rclpy.node",
        "rclpy.lifecycle",
        "rclpy.lifecycle.node",
        "bonbon_msgs",
        "bonbon_msgs.msg",
        "bonbon_srvs",
        "bonbon_srvs.srv",
        "std_msgs",
        "std_msgs.msg",
        "lifecycle_msgs",
        "lifecycle_msgs.msg",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    from unittest.mock import MagicMock

    for attr in (
        "LLMResponse",
        "LLMLog",
        "BehaviorRecommendation",
        "TTSRequest",
        "IntentResult",
        "RiskAssessment",
        "SceneSummary",
    ):
        setattr(sys.modules["bonbon_msgs.msg"], attr, MagicMock)
    for attr in ("LLMQuery",):
        setattr(sys.modules["bonbon_srvs.srv"], attr, MagicMock)
    for attr in ("Header",):
        setattr(sys.modules["std_msgs.msg"], attr, MagicMock)
    for attr in ("State",):
        setattr(sys.modules["lifecycle_msgs.msg"], attr, MagicMock)


_stub()

from bonbon_llm.config.llm_config import (
    HallucinationConfig,
    PersonalityConfig,
    RAGConfig,
    SafetyFilterConfig,
)
from bonbon_llm.core.rag_retriever import RAGRetriever
from bonbon_llm.personality.personality_layer import PersonalityLayer
from bonbon_llm.safety.authorization import SAFETY_NORMAL, SafetySnapshot
from bonbon_llm.safety.command_filter import SafetyCommandFilter
from bonbon_llm.safety.hallucination_guard import HallucinationGuard
from bonbon_llm.tools.tool_registry import ToolRegistry

STRICT = os.getenv("STRICT", "0") == "1"


# ── Benchmark harness ─────────────────────────────────────────────────────────


def _bench(fn: Callable, n: int = 1000, label: str = "") -> dict:
    """Run fn n times and compute latency statistics."""
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)

    samples.sort()
    p50 = statistics.median(samples)
    p95 = samples[int(0.95 * len(samples))]
    p99 = samples[int(0.99 * len(samples))]
    mean = statistics.mean(samples)

    print(
        f"  {label:40s}  "
        f"p50={p50:6.2f}ms  p95={p95:6.2f}ms  p99={p99:6.2f}ms  "
        f"mean={mean:6.2f}ms  (n={n})"
    )

    return {"p50": p50, "p95": p95, "p99": p99, "mean": mean}


# ── Component benchmarks ───────────────────────────────────────────────────────


def bench_safety_filter() -> dict:
    filt = SafetyCommandFilter(SafetyFilterConfig())
    texts = [
        "Hello! The latte is S$5.00.",
        "Please navigate to table 3 for me.",
        "What is the menu today?",
        "Can you bring the espresso?",
        "publish cmd_vel twist message directly",  # blocked
    ]
    idx = [0]

    def fn():
        filt.filter_text(texts[idx[0] % len(texts)])
        idx[0] += 1

    return _bench(fn, n=10_000, label="SafetyCommandFilter.filter_text")


def bench_hallucination_guard() -> dict:
    guard = HallucinationGuard(HallucinationConfig(enabled=True))
    texts = [
        "The latte is S$5.00.",
        "I can fly to your table instantly!",
        "Hello! Welcome to the café.",
        "I have arms to carry your order.",
        "Our espresso is freshly brewed.",
    ]
    idx = [0]

    def fn():
        guard.check(texts[idx[0] % len(texts)])
        idx[0] += 1

    return _bench(fn, n=10_000, label="HallucinationGuard.check")


def bench_personality_layer() -> dict:
    cfg = PersonalityConfig(name="BonBon", max_response_words=40)
    layer = PersonalityLayer(cfg)
    texts = [
        "The **latte** is S$5.00. Would you like one?",
        "## Menu\n- Espresso: S$3.50\n- Latte: S$5.00",
        "I travel at 0.5 m/s for your safety.",
        "Hello! Welcome to the café. What can I get you today?",
    ]
    idx = [0]

    def fn():
        layer.apply(texts[idx[0] % len(texts)])
        idx[0] += 1

    return _bench(fn, n=10_000, label="PersonalityLayer.apply")


def bench_rag_retriever() -> dict:
    rag = RAGRetriever(RAGConfig(backend="numpy", top_k=5, similarity_threshold=0.0))
    rag.load()
    queries = [
        "latte price menu",
        "safety rules navigation",
        "table location café layout",
        "emergency 995 staff",
        "operating hours tuesday",
    ]
    idx = [0]

    def fn():
        rag.retrieve(queries[idx[0] % len(queries)])
        idx[0] += 1

    return _bench(fn, n=1_000, label="RAGRetriever.retrieve (NumPy, k=5)")


def bench_tool_registry_readonly() -> dict:
    snap = SafetySnapshot.safe_default()
    snap.state_id = SAFETY_NORMAL
    snap.state_name = "NORMAL"

    reg = ToolRegistry(
        safety_filter=SafetyCommandFilter(SafetyFilterConfig()),
        scene_provider=lambda: "2 persons near counter.",
        safety_provider=lambda: snap,
        memory_provider=lambda q, k: ["Memory result"],
        tts_dispatcher=lambda t, p: None,
        behavior_dispatcher=lambda bc, ps, c: None,
    )
    calls = [
        ("get_scene_context", {}),
        ("get_safety_state", {}),
        ("query_memory", {"query": "previous order", "k": 3}),
    ]
    idx = [0]

    def fn():
        name, args = calls[idx[0] % len(calls)]
        reg.dispatch(name, args)
        idx[0] += 1

    return _bench(fn, n=5_000, label="ToolRegistry.dispatch (read-only)")


def bench_full_pipeline_no_llm() -> dict:
    """
    Full pipeline excluding Ollama call:
    RAG retrieve → safety filter → hallucination guard → personality apply
    """
    from bonbon_llm.core.rag_retriever import RAGRetriever

    rag = RAGRetriever(RAGConfig(backend="numpy", top_k=3, similarity_threshold=0.0))
    rag.load()

    filt = SafetyCommandFilter(SafetyFilterConfig())
    guard = HallucinationGuard(HallucinationConfig(enabled=True))
    pers = PersonalityLayer(PersonalityConfig(name="BonBon", max_response_words=40))

    llm_responses = [
        "The latte is S$5.00. Would you like one?",
        "Hello! Welcome to BonBon café.",
        "I can navigate to table 3 for you.",
    ]
    queries = [
        "latte price",
        "greeting",
        "navigate table 3",
    ]
    idx = [0]

    def fn():
        i = idx[0] % len(queries)
        rag_results = rag.retrieve_with_scores(queries[i])
        raw = llm_responses[i]
        filt_result = filt.filter_text(raw)
        if filt_result.sanitized_text:
            guard.check(filt_result.sanitized_text, rag_results, 0.88)
            pers.apply(filt_result.sanitized_text)
        idx[0] += 1

    return _bench(fn, n=500, label="Full pipeline (no LLM)")


# ── Budget checks ─────────────────────────────────────────────────────────────

BUDGETS = {
    "filter": 1.0,  # ms p99
    "guard": 1.0,
    "personality": 2.0,
    "rag": 50.0,
    "tools": 5.0,
    "pipeline": 75.0,
}


def run_all():
    print("\n" + "=" * 80)
    print("bonbon_llm latency benchmarks")
    print("=" * 80)

    results = {
        "filter": bench_safety_filter(),
        "guard": bench_hallucination_guard(),
        "personality": bench_personality_layer(),
        "rag": bench_rag_retriever(),
        "tools": bench_tool_registry_readonly(),
        "pipeline": bench_full_pipeline_no_llm(),
    }

    print("\n" + "=" * 80)
    print("Budget check (p99):")
    violations = []
    for key, budget_ms in BUDGETS.items():
        p99 = results[key]["p99"]
        status = "✓" if p99 <= budget_ms else "✗ VIOLATION"
        print(f"  {key:20s}  p99={p99:6.2f}ms  budget={budget_ms:.1f}ms  {status}")
        if p99 > budget_ms:
            violations.append(f"{key}: p99={p99:.2f}ms > {budget_ms}ms")

    if violations:
        msg = "Budget violations:\n" + "\n".join(violations)
        if STRICT:
            raise AssertionError(msg)
        else:
            print("\nWARNING (set STRICT=1 to fail on violations):")
            print(msg)
    else:
        print("\nAll components within budget.")

    print("=" * 80 + "\n")


# ── pytest entry points ───────────────────────────────────────────────────────


def test_safety_filter_p99():
    result = bench_safety_filter()
    assert (
        result["p99"] < BUDGETS["filter"] * 10
    ), f"SafetyCommandFilter p99 {result['p99']:.2f}ms > {BUDGETS['filter']*10}ms"


def test_hallucination_guard_p99():
    result = bench_hallucination_guard()
    assert result["p99"] < BUDGETS["guard"] * 10


def test_personality_layer_p99():
    result = bench_personality_layer()
    assert result["p99"] < BUDGETS["personality"] * 10


def test_rag_retriever_p99():
    result = bench_rag_retriever()
    assert result["p99"] < BUDGETS["rag"] * 10


def test_full_pipeline_p99():
    result = bench_full_pipeline_no_llm()
    assert result["p99"] < BUDGETS["pipeline"] * 5


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_all()
