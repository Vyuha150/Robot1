# Edge AI Caching Report

Phase 15 summary of Phase 6's deliverable:
[`cache_manager.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/cache_manager.py).

## What's new vs. what's reused

Per [`docs/DUPLICATE_PIPELINE_AUDIT.md`](DUPLICATE_PIPELINE_AUDIT.md), real
caches already existed for LLM responses
(`bonbon_llm.core.response_cache.ResponseCache`) and TTS phrase audio
(`TTSRouter`'s `HOSPITAL_PHRASE_CACHE_KEYS` + `models/tts_cache/`). This
module does not rebuild either — it adds the two things this brief's
Phase 6 needed that didn't exist:

1. **`RagResultCache`** (GAP-E11, fixed) — a genuinely new bounded
   LRU+TTL cache for RAG retrieval results specifically, distinct from
   the LLM answer cache (pure retrieval has a `privacy_safe` gate
   instead of a safety-filter/hallucination-guard status to key on).
2. **`CacheManager`** — a unified `cache_hit`/`cache_miss`/
   `latency_saved_ms`/`cache_item_type`/`privacy_safe` metrics event log
   spanning LLM/TTS/RAG/embedding/FAQ caching, which no existing
   per-package cache exposed on its own — required for Phase 12's
   dashboard cache card.

## Cache policy rules enforced

- **Privacy-safe only**: `RagResultCache.put(..., privacy_safe=False)`
  is refused outright, never silently cached anyway — a patient-specific
  query is never cached.
- **TTL-based invalidation**: entries expire after `ttl_sec` (config:
  [`config/edge_ai/cache_policy.yaml`](../config/edge_ai/cache_policy.yaml)),
  verified expired entries are actually evicted on access, not just
  logically stale.
- **LLM/TTS caches remain owned by their existing packages** — this
  module does not take ownership away from `ResponseCache`/`TTSRouter`;
  callers report hit/miss events here via `record()` so the dashboard has
  one aggregate view without a second competing cache instance.

## Verification

`tests/edge_ai/test_cache_manager.py` — 7 tests: miss→put→hit round
trip, privacy-unsafe queries never cached, TTL expiry, LRU eviction at
`max_entries`, metrics aggregation with all 5 required fields, `rag_get`/
`rag_put` recording correctly, `CacheEvent.to_dict()`'s field contract.
`tests/edge_ai/test_task_router.py` and
`test_event_driven_processing.py` additionally confirm `TaskRouter`'s
FAQ branch actually consults this cache before falling to RAG.
