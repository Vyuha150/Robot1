"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.cache_manager.
Covers RagResultCache (the genuinely new cache, GAP-E11) and
CacheManager's unified metrics (cache_hit, cache_miss, latency_saved_ms,
cache_item_type, privacy_safe -- Phase 6 requirement)."""

from __future__ import annotations

import unittest


class TestRagResultCache(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.cache_manager import RagResultCache

        self.cache = RagResultCache(ttl_sec=10.0)

    def test_miss_then_put_then_hit(self):
        self.assertIsNone(self.cache.get("where is radiology", "faq"))
        self.cache.put("where is radiology", "faq", ["Radiology is on floor 2"])
        hit = self.cache.get("where is radiology", "faq")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.documents, ["Radiology is on floor 2"])

    def test_privacy_unsafe_query_is_never_cached(self):
        stored = self.cache.put("what is patient 12345's diagnosis", "patient_lookup", ["..."], privacy_safe=False)
        self.assertFalse(stored)
        self.assertIsNone(self.cache.get("what is patient 12345's diagnosis", "patient_lookup"))

    def test_entry_expires_after_ttl(self):
        self.cache.put("q", "ctx", ["doc"], now=0.0)
        self.assertIsNotNone(self.cache.get("q", "ctx", now=5.0))
        self.assertIsNone(self.cache.get("q", "ctx", now=20.0))  # past the 10s TTL

    def test_lru_eviction_respects_max_entries(self):
        from bonbon_edge_ai_runtime.cache_manager import RagResultCache

        small = RagResultCache(max_entries=2, ttl_sec=100.0)
        small.put("a", "ctx", ["doc-a"])
        small.put("b", "ctx", ["doc-b"])
        small.put("c", "ctx", ["doc-c"])  # evicts "a"
        self.assertIsNone(small.get("a", "ctx"))
        self.assertIsNotNone(small.get("c", "ctx"))


class TestCacheManagerMetrics(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager

        self.manager = CacheManager()

    def test_metrics_have_required_fields(self):
        self.manager.record("llm", hit=True, latency_saved_ms=800.0, privacy_safe=True)
        self.manager.record("tts", hit=False, privacy_safe=True)
        metrics = self.manager.metrics()
        self.assertIn("byItemType", metrics)
        self.assertIn("llm", metrics["byItemType"])
        self.assertEqual(metrics["byItemType"]["llm"]["hits"], 1)
        self.assertEqual(metrics["byItemType"]["tts"]["misses"], 1)
        self.assertEqual(metrics["byItemType"]["llm"]["latencySavedMsTotal"], 800.0)

    def test_rag_get_and_put_go_through_and_are_recorded(self):
        self.assertIsNone(self.manager.rag_get("where is icu", "faq"))
        self.manager.rag_put("where is icu", "faq", ["ICU is on floor 3"])
        result = self.manager.rag_get("where is icu", "faq", estimated_latency_saved_ms=120.0)
        self.assertIsNotNone(result)
        metrics = self.manager.metrics()
        self.assertEqual(metrics["byItemType"]["rag"]["hits"], 1)
        self.assertEqual(metrics["byItemType"]["rag"]["misses"], 1)

    def test_cache_event_to_dict_has_all_required_fields(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheEvent

        event = CacheEvent(item_type="tts", hit=True, latency_saved_ms=50.0, privacy_safe=True)
        as_dict = event.to_dict()
        for field in ("itemType", "hit", "latencySavedMs", "privacySafe", "timestamp"):
            self.assertIn(field, as_dict)


if __name__ == "__main__":
    unittest.main()
