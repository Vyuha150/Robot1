"""Tests for ResponseCache — safety-first caching of repeated LLM queries."""

from __future__ import annotations

from bonbon_llm.core.response_cache import ResponseCache


class TestBasicCaching:
    def test_miss_on_empty_cache(self):
        cache = ResponseCache()
        assert cache.get("what time is it", "ctx_a") is None

    def test_hit_after_put(self):
        cache = ResponseCache()
        cache.put("what time is it", "ctx_a", "It's 3pm.", "ok")
        hit = cache.get("what time is it", "ctx_a")
        assert hit is not None
        assert hit.text == "It's 3pm."

    def test_question_is_case_and_whitespace_insensitive(self):
        cache = ResponseCache()
        cache.put("What time is it", "ctx_a", "It's 3pm.", "ok")
        hit = cache.get("  what time is it  ", "ctx_a")
        assert hit is not None


class TestContextSensitivity:
    def test_different_context_is_a_miss(self):
        """Same question, different scene/safety context -- must NOT serve
        the cached answer, since the correct answer may have changed."""
        cache = ResponseCache()
        cache.put("what do you see", "ctx_kitchen_empty", "Nothing nearby.", "ok")
        hit = cache.get("what do you see", "ctx_kitchen_person_present")
        assert hit is None

    def test_same_question_same_context_is_a_hit(self):
        cache = ResponseCache()
        cache.put("what do you see", "ctx_kitchen_empty", "Nothing nearby.", "ok")
        hit = cache.get("what do you see", "ctx_kitchen_empty")
        assert hit is not None


class TestCacheableStatusGating:
    def test_llm_error_is_never_cached(self):
        cache = ResponseCache()
        stored = cache.put("q", "ctx", "fallback text", "llm_error")
        assert stored is False
        assert cache.get("q", "ctx") is None

    def test_safety_block_is_never_cached(self):
        cache = ResponseCache()
        stored = cache.put("q", "ctx", "fallback text", "safety_block")
        assert stored is False
        assert cache.get("q", "ctx") is None

    def test_hallucination_is_never_cached(self):
        cache = ResponseCache()
        stored = cache.put("q", "ctx", "fallback text", "hallucination")
        assert stored is False
        assert cache.get("q", "ctx") is None

    def test_ok_status_is_cached(self):
        cache = ResponseCache()
        stored = cache.put("q", "ctx", "a real answer", "ok")
        assert stored is True


class TestTTL:
    def test_entry_expires_after_ttl(self):
        cache = ResponseCache(ttl_sec=10.0)
        cache.put("q", "ctx", "answer", "ok", now=1000.0)
        assert cache.get("q", "ctx", now=1005.0) is not None
        assert cache.get("q", "ctx", now=1011.0) is None

    def test_expired_entry_is_evicted_not_just_ignored(self):
        cache = ResponseCache(ttl_sec=10.0)
        cache.put("q", "ctx", "answer", "ok", now=1000.0)
        cache.get("q", "ctx", now=1011.0)  # triggers eviction
        assert cache.size == 0


class TestBoundedSize:
    def test_lru_eviction_when_over_capacity(self):
        cache = ResponseCache(max_entries=2)
        cache.put("q1", "ctx", "a1", "ok")
        cache.put("q2", "ctx", "a2", "ok")
        cache.put("q3", "ctx", "a3", "ok")
        assert cache.size == 2
        assert cache.get("q1", "ctx") is None  # oldest evicted
        assert cache.get("q3", "ctx") is not None

    def test_get_refreshes_lru_order(self):
        cache = ResponseCache(max_entries=2)
        cache.put("q1", "ctx", "a1", "ok")
        cache.put("q2", "ctx", "a2", "ok")
        cache.get("q1", "ctx")  # q1 now most-recently-used
        cache.put("q3", "ctx", "a3", "ok")  # should evict q2, not q1
        assert cache.get("q1", "ctx") is not None
        assert cache.get("q2", "ctx") is None


class TestStats:
    def test_hit_rate_tracks_hits_and_misses(self):
        cache = ResponseCache()
        cache.get("q", "ctx")  # miss
        cache.put("q", "ctx", "a", "ok")
        cache.get("q", "ctx")  # hit
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_clear_resets_size(self):
        cache = ResponseCache()
        cache.put("q", "ctx", "a", "ok")
        cache.clear()
        assert cache.size == 0
