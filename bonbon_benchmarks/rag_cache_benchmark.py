"""Cache-efficiency benchmarking across the 7 cache types Phase 6 names.
Reuses the real cache implementations directly -- does not reimplement
any of them:

  - RAG retrieval cache:    bonbon_edge_ai_runtime.cache_manager.RagResultCache
  - LLM safe-response cache: bonbon_llm.core.response_cache.ResponseCache
  - TTS phrase cache:       bonbon_speech_ai.tts_router's HOSPITAL_PHRASE_CACHE_KEYS
                            (cached-path lookup timing, not audio playback)
  - FAQ cache:              the RAG cache above, keyed on FAQ-shaped queries
                            (no separate FAQ-only cache class exists)

Honestly reported as NOT applicable, per cache_manager.py's own design
docstring and a direct repo search, rather than fabricated:

  - doctor-room lookup cache:     deliberately NOT cached -- recomputed
                                   from source of truth every call (no
                                   invalidation needed on admin update)
  - semantic map location cache:  same reasoning, not cached by design
  - ASR phrase correction cache:  does not exist anywhere in the repo
                                   (confirmed via repo-wide search) --
                                   a genuine gap, not a design decision
"""

from __future__ import annotations

import time

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import (
    BenchmarkCategoryReport,
    BenchmarkMetric,
    MetricSampler,
)


def _time_calls(fn, iterations: int) -> MetricSampler:
    sampler = MetricSampler()
    for _ in range(iterations):
        started = time.perf_counter()
        fn()
        sampler.record((time.perf_counter() - started) * 1000.0)
    return sampler


def benchmark_rag_cache(iterations: int = 200) -> tuple[BenchmarkMetric, BenchmarkMetric, float]:
    """Returns (cold_metric, warm_metric, hit_rate)."""
    from bonbon_edge_ai_runtime.cache_manager import RagResultCache

    cache = RagResultCache()
    cold_sampler = _time_calls(lambda: cache.get(f"q-{time.perf_counter_ns()}", "faq"), iterations)
    cache.put("where is radiology", "faq", ["Radiology is on floor 2"])
    warm_sampler = _time_calls(lambda: cache.get("where is radiology", "faq"), iterations)

    cold = BenchmarkMetric.from_sampler(
        cold_sampler, metric_name="rag_cache_cold_latency", board="ai_pi", module="rag_cache",
        scenario=f"guaranteed-miss lookup x{iterations}", unit="ms",
    )
    warm = BenchmarkMetric.from_sampler(
        warm_sampler, metric_name="rag_cache_warm_latency", board="ai_pi", module="rag_cache",
        scenario=f"repeated hit lookup x{iterations}", unit="ms",
        recommendation=f"hit_rate={cache.hit_rate:.1%} on this synthetic access pattern (not representative of real query distribution).",
    )
    return cold, warm, cache.hit_rate


def benchmark_llm_response_cache(iterations: int = 200) -> tuple[BenchmarkMetric, BenchmarkMetric, float]:
    from bonbon_llm.core.response_cache import ResponseCache

    cache = ResponseCache()
    cold_sampler = _time_calls(lambda: cache.get(f"q-{time.perf_counter_ns()}", "ctx"), iterations)
    cache.put("who are you", "ctx", "I am BonBon, a hospital service robot.", "ok")
    warm_sampler = _time_calls(lambda: cache.get("who are you", "ctx"), iterations)

    cold = BenchmarkMetric.from_sampler(
        cold_sampler, metric_name="llm_response_cache_cold_latency", board="ai_pi", module="llm_cache",
        scenario=f"guaranteed-miss lookup x{iterations}", unit="ms",
    )
    warm = BenchmarkMetric.from_sampler(
        warm_sampler, metric_name="llm_response_cache_warm_latency", board="ai_pi", module="llm_cache",
        scenario=f"repeated hit lookup x{iterations}", unit="ms",
        recommendation=f"hit_rate={cache.hit_rate:.1%} on this synthetic access pattern; a hit skips both RAG retrieval and the LLM call entirely.",
    )
    return cold, warm, cache.hit_rate


def benchmark_tts_phrase_cache_lookup(iterations: int = 200) -> BenchmarkMetric:
    try:
        from bonbon_speech_ai.tts_router import HOSPITAL_PHRASE_CACHE_KEYS
    except ImportError as exc:
        return BenchmarkMetric.blocked(
            metric_name="tts_phrase_cache_key_lookup", board="ai_pi", module="tts_cache",
            scenario="phrase_key membership check", reason=f"bonbon_speech_ai not importable: {exc}",
        )
    if not HOSPITAL_PHRASE_CACHE_KEYS:
        return BenchmarkMetric.blocked(
            metric_name="tts_phrase_cache_key_lookup", board="ai_pi", module="tts_cache",
            scenario="phrase_key membership check", reason="HOSPITAL_PHRASE_CACHE_KEYS is empty",
        )
    sample_key = HOSPITAL_PHRASE_CACHE_KEYS[0]
    sampler = _time_calls(lambda: sample_key in HOSPITAL_PHRASE_CACHE_KEYS, iterations)
    return BenchmarkMetric.from_sampler(
        sampler, metric_name="tts_phrase_cache_key_lookup", board="ai_pi", module="tts_cache",
        scenario=f"cache-key membership check x{iterations}", unit="ms",
        recommendation="This times the key-lookup only, not actual cached-WAV file I/O or audio playback (no audio device in this environment) -- see speech_benchmark.benchmark_tts_cached_phrase.",
    )


def not_cached_by_design(name: str, module: str) -> BenchmarkMetric:
    return BenchmarkMetric.blocked(
        metric_name=name, board="ai_pi", module=module, scenario="lookup", unit="ms",
        reason="deliberately not cached by design -- recomputed from source of truth on every call, no invalidation needed (see bonbon_edge_ai_runtime.cache_manager module docstring)",
        recommendation="No action needed -- this is a design decision, not a gap.",
    )


def not_implemented(name: str, module: str) -> BenchmarkMetric:
    return BenchmarkMetric.blocked(
        metric_name=name, board="ai_pi", module=module, scenario="lookup", unit="ms",
        reason="no such cache exists anywhere in the repo (confirmed by direct search) -- a genuine gap, not a design decision",
        recommendation="Consider adding a bounded LRU+TTL correction cache in bonbon_speech_ai if repeated corrections for the same phrase are observed in the field.",
    )


def run_all() -> BenchmarkCategoryReport:
    report = BenchmarkCategoryReport(category="cache_efficiency")
    rag_cold, rag_warm, _ = benchmark_rag_cache()
    report.add(rag_cold)
    report.add(rag_warm)
    llm_cold, llm_warm, _ = benchmark_llm_response_cache()
    report.add(llm_cold)
    report.add(llm_warm)
    report.add(benchmark_tts_phrase_cache_lookup())
    report.add(not_cached_by_design("doctor_room_lookup_cache", "hospital_directory"))
    report.add(not_cached_by_design("semantic_map_location_cache", "navigation"))
    report.add(not_implemented("asr_phrase_correction_cache", "asr"))
    # FAQ cache: the RAG cache keyed on FAQ-shaped queries -- no separate class.
    faq_cold, faq_warm, _ = benchmark_rag_cache()
    faq_cold.metric_name, faq_warm.metric_name = "faq_cache_cold_latency", "faq_cache_warm_latency"
    faq_cold.recommendation = faq_warm.recommendation = "FAQ cache is the same RagResultCache keyed on FAQ-shaped queries -- no separate FAQ-only cache class exists."
    report.add(faq_cold)
    report.add(faq_warm)
    return report
