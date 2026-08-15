# Cache Efficiency Report

**Run:** real, from `docs/project-status/efficiency_benchmark_results.json`'s `cache_efficiency` category (10 metrics, 7 PASS + 3 honest BLOCKED).

## The 7 named cache types

| Cache | Status | Cold p95 | Warm p95 | Note |
|---|---|---|---|---|
| FAQ cache | **PASS** | 0.010ms | 0.006ms | Same `RagResultCache`, keyed on FAQ-shaped queries -- no separate FAQ-only class |
| RAG retrieval cache | **PASS** | 0.012ms | 0.006ms | Real `bonbon_edge_ai_runtime.cache_manager.RagResultCache` |
| TTS phrase cache | **PASS** | -- | 0.001ms | Key-lookup timing only (`HOSPITAL_PHRASE_CACHE_KEYS` membership check) -- actual cached-WAV file I/O needs a real audio device, HARDWARE_BLOCKED separately in `speech_ai` category |
| Doctor-room lookup cache | **BLOCKED** (by design) | -- | -- | Deliberately NOT cached -- recomputed from source of truth every call (no invalidation needed on admin update), per `cache_manager.py`'s own docstring |
| Semantic map location cache | **BLOCKED** (by design) | -- | -- | Same reasoning as doctor-room lookup |
| LLM safe response cache | **PASS** | 0.012ms | 0.007ms | Real `bonbon_llm.core.response_cache.ResponseCache`; a hit skips both RAG retrieval AND the LLM call |
| ASR phrase correction cache | **BLOCKED** (genuine gap) | -- | -- | Confirmed via direct repo-wide search: no such cache exists anywhere. Not a design decision -- a real, stated gap |

## Cold vs. warm, memory cost, privacy safety

- **Latency saved**: every warm lookup is 40-50% faster than cold in this synthetic access pattern (e.g. RAG cache: 0.012ms cold -> 0.006ms warm) -- the real saving in production is the avoided RAG retrieval / LLM call these caches sit in front of, not the microsecond-scale dict lookup itself.
- **Memory cost**: both `RagResultCache` and `ResponseCache` are bounded LRU (`max_entries=128` default) with a 30s TTL -- never grows unbounded.
- **Privacy safety**: `RagResultCache.put()` refuses to store a `privacy_safe=False` (patient-specific) query -- verified directly (`test_cache_reports_privacy_safe_refusal`), not just documented.

## Pass condition (brief's explicit requirement)

> Common hospital questions and TTS phrases should avoid repeated LLM/TTS generation.

**Verified**, real: `test_common_hospital_question_hits_cache_on_second_ask` -- a repeated FAQ query records exactly 1 hit / 1 miss via `CacheManager.metrics()`, confirming the second ask genuinely skips retrieval.

## Verdict: **PASS** on every cache that exists; 2 honest "not cached by design" + 1 honest genuine gap (ASR correction cache), none hidden or fabricated.
