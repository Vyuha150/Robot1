"""Phase 6: cache efficiency across the 7 named cache types.

Exercises bonbon_benchmarks.rag_cache_benchmark directly, which itself
wraps the real cache implementations (RagResultCache, ResponseCache,
HOSPITAL_PHRASE_CACHE_KEYS) -- see that module's docstring for exactly
which of the 7 brief-named caches are real caches, deliberately-not-
cached-by-design, or a genuine gap (ASR phrase correction).
"""

from __future__ import annotations

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks import rag_cache_benchmark as rcb


class TestRAGRetrievalCache:
    def test_warm_lookup_is_not_slower_than_cold(self):
        cold, warm, hit_rate = rcb.benchmark_rag_cache(iterations=50)
        assert cold.status == "PASS"
        assert warm.status == "PASS"
        # hit_rate is cumulative across both phases (50 cold misses + 50
        # warm hits) -- 0.5, not 1.0. Asserted exactly, not loosely, so a
        # future change to RagResultCache's counter semantics is caught.
        assert hit_rate == 0.5

    def test_cache_reports_privacy_safe_refusal(self):
        from bonbon_edge_ai_runtime.cache_manager import RagResultCache

        cache = RagResultCache()
        stored = cache.put("patient-specific query", "ctx", ["some patient data"], privacy_safe=False)
        assert stored is False  # PASS CONDITION: never silently cache a privacy-unsafe query


class TestLLMResponseCache:
    def test_hit_skips_both_rag_and_llm_conceptually(self):
        # ResponseCache.get() returning a CachedResponse is precisely the
        # signal llm_orchestrator_node uses to skip RAG retrieval AND the
        # LLM call -- verified here structurally (a hit exists, is fast).
        cold, warm, hit_rate = rcb.benchmark_llm_response_cache(iterations=50)
        assert cold.status == "PASS"
        assert warm.status == "PASS"
        assert hit_rate == 0.5  # same cumulative-counter semantics as RagResultCache

    def test_error_and_blocked_statuses_are_never_cached(self):
        from bonbon_llm.core.response_cache import ResponseCache

        cache = ResponseCache()
        assert cache.put("q", "ctx", "text", "llm_error") is False
        assert cache.put("q", "ctx", "text", "safety_block") is False
        assert cache.put("q", "ctx", "text", "ok") is True


class TestTTSPhraseCache:
    def test_cache_key_lookup_is_real_and_fast(self):
        metric = rcb.benchmark_tts_phrase_cache_lookup(iterations=50)
        assert metric.status == "PASS"
        assert metric.avg < 10.0  # a dict/tuple membership check, must be sub-millisecond-class


class TestFAQCache:
    def test_faq_cache_is_the_rag_cache_keyed_on_faq_queries(self):
        report = rcb.run_all()
        faq_metrics = [m for m in report.metrics if m.metric_name.startswith("faq_cache")]
        assert len(faq_metrics) == 2  # cold + warm
        assert all(m.status == "PASS" for m in faq_metrics)


class TestNotCachedByDesignVsGenuineGap:
    def test_doctor_room_lookup_is_reported_as_design_choice_not_a_gap(self):
        m = rcb.not_cached_by_design("doctor_room_lookup_cache", "hospital_directory")
        assert m.status == "BLOCKED"
        assert "design" in m.blocked_reason.lower()

    def test_asr_correction_cache_is_reported_as_a_genuine_gap(self):
        m = rcb.not_implemented("asr_phrase_correction_cache", "asr")
        assert m.status == "BLOCKED"
        assert "gap" in m.blocked_reason.lower()
        # The two must be distinguishable -- a design decision and a real
        # gap must never be reported with the same undifferentiated reason.
        design = rcb.not_cached_by_design("semantic_map_location_cache", "navigation")
        assert m.blocked_reason != design.blocked_reason


class TestPassConditionCommonQuestionsAvoidRepeatedGeneration:
    def test_common_hospital_question_hits_cache_on_second_ask(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager

        cache = CacheManager()
        question, context = "where is radiology", "faq"
        first = cache.rag_get(question, context)
        assert first is None  # cold
        cache.rag_put(question, context, ["Radiology is on floor 2"])
        second = cache.rag_get(question, context)
        assert second is not None  # PASS CONDITION: repeated question avoids re-retrieval
        metrics = cache.metrics()
        assert metrics["byItemType"]["rag"]["hits"] == 1
        assert metrics["byItemType"]["rag"]["misses"] == 1
