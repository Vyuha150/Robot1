"""bonbon_edge_ai_runtime.cache_manager -- Edge AI Runtime brief Phase
6. Per docs/DUPLICATE_PIPELINE_AUDIT.md, real caches already exist for
LLM responses (bonbon_llm.core.response_cache.ResponseCache) and TTS
phrase audio (bonbon_speech_ai.tts_router's HOSPITAL_PHRASE_CACHE_KEYS +
models/tts_cache/). This module does not rebuild either. It adds the
two things that didn't exist before:

1. RagResultCache -- a genuinely new RAG-retrieval result cache (GAP-E11
   in docs/EDGE_AI_GAP_ANALYSIS.md). The existing LLM ResponseCache only
   indirectly skips RAG on an LLM-answer cache hit; there was no cache
   for RAG retrieval itself.
2. CacheManager -- a unified metrics event log (cache_hit, cache_miss,
   latency_saved_ms, cache_item_type, privacy_safe) spanning LLM/TTS/RAG
   caching, which this brief's Phase 6 requires for dashboard visibility
   and none of the existing per-package caches expose on their own.

Cache policy (brief's explicit rules):
  - Deterministic hospital data (FAQ, doctor/department/room lookups)
    is handled by bonbon_llm's own deterministic resolver, not cached
    here -- there's nothing to invalidate on admin update since it's
    recomputed from the source of truth every call.
  - RAG results here are cached only when privacy_safe=True; a caller
    passing privacy_safe=False (a patient-specific query) is refused,
    not silently cached anyway.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field


@dataclass
class RagCachedResult:
    documents: list
    cached_at: float


class RagResultCache:
    """Same bounded LRU+TTL shape as bonbon_llm.core.response_cache.ResponseCache,
    deliberately a separate class rather than reusing ResponseCache
    directly: RAG results and LLM answers have different cacheability
    rules (pure retrieval has no safety-filter/hallucination-guard
    status to gate on; it has a privacy_safe flag instead)."""

    def __init__(self, max_entries: int = 128, ttl_sec: float = 30.0) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl_sec = ttl_sec
        self._entries: OrderedDict[str, RagCachedResult] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(query: str, context: str) -> str:
        raw = f"{query.strip().lower()}||{context}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, query: str, context: str, now: float | None = None) -> RagCachedResult | None:
        now = now if now is not None else time.monotonic()
        key = self.make_key(query, context)
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        if (now - entry.cached_at) > self._ttl_sec:
            del self._entries[key]
            self._misses += 1
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return entry

    def put(
        self,
        query: str,
        context: str,
        documents: list,
        *,
        privacy_safe: bool = True,
        now: float | None = None,
    ) -> bool:
        """Returns True if stored. A patient-specific query
        (privacy_safe=False) is refused, never silently cached."""
        if not privacy_safe:
            return False
        now = now if now is not None else time.monotonic()
        key = self.make_key(query, context)
        self._entries[key] = RagCachedResult(documents=documents, cached_at=now)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return True

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    @property
    def size(self) -> int:
        return len(self._entries)


@dataclass
class CacheEvent:
    item_type: str  # "llm" | "tts" | "rag" | "embedding" | "faq"
    hit: bool
    latency_saved_ms: float
    privacy_safe: bool
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        return {
            "itemType": self.item_type,
            "hit": self.hit,
            "latencySavedMs": self.latency_saved_ms,
            "privacySafe": self.privacy_safe,
            "timestamp": self.timestamp,
        }


class CacheManager:
    """Unified metrics + the new RAG result cache. LLM/TTS caches are
    NOT owned here -- callers (llm_orchestrator_node, TTSRouter) keep
    owning their own ResponseCache/phrase-cache instances (they already
    work correctly) and just report hit/miss events here via record()
    so the dashboard has one place to read aggregate cache metrics from,
    per this brief's Phase 12 requirement."""

    def __init__(self, *, rag_cache: RagResultCache | None = None, event_log_size: int = 500) -> None:
        self.rag_cache = rag_cache or RagResultCache()
        self._events: deque[CacheEvent] = deque(maxlen=event_log_size)

    def record(
        self,
        item_type: str,
        hit: bool,
        *,
        latency_saved_ms: float = 0.0,
        privacy_safe: bool = True,
    ) -> None:
        self._events.append(
            CacheEvent(item_type=item_type, hit=hit, latency_saved_ms=latency_saved_ms, privacy_safe=privacy_safe)
        )

    def rag_get(self, query: str, context: str, *, estimated_latency_saved_ms: float = 0.0):
        result = self.rag_cache.get(query, context)
        self.record("rag", hit=result is not None, latency_saved_ms=estimated_latency_saved_ms if result else 0.0)
        return result

    def rag_put(self, query: str, context: str, documents: list, *, privacy_safe: bool = True) -> bool:
        return self.rag_cache.put(query, context, documents, privacy_safe=privacy_safe)

    def metrics(self) -> dict:
        """Aggregate hit/miss/latency-saved per item_type, from the
        recorded event log -- includes item types this manager doesn't
        own the cache for (llm, tts), as long as their owners call
        record()."""
        by_type: dict[str, dict] = {}
        for event in self._events:
            bucket = by_type.setdefault(
                event.item_type, {"hits": 0, "misses": 0, "latencySavedMsTotal": 0.0}
            )
            if event.hit:
                bucket["hits"] += 1
                bucket["latencySavedMsTotal"] += event.latency_saved_ms
            else:
                bucket["misses"] += 1
        for bucket in by_type.values():
            total = bucket["hits"] + bucket["misses"]
            bucket["hitRate"] = bucket["hits"] / total if total else 0.0
        return {
            "byItemType": by_type,
            "ragCacheSize": self.rag_cache.size,
            "ragCacheHitRate": self.rag_cache.hit_rate,
            "totalEvents": len(self._events),
        }
