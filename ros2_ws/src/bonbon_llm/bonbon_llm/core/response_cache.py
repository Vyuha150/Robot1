"""ResponseCache — bounded, TTL'd cache for repeated LLM queries.

Addresses a real gap (no LLM/RAG response caching exists anywhere in this
project): identical (question, context) pairs arriving within a short
window currently re-run the full RAG retrieval + LLM call every time.

Safety-first design, not a generic cache:
  - The key includes the FULL context string (scene + safety snapshot), not
    just the question text. The same question can warrant a different
    answer when the scene or safety state has changed, so any change to
    either automatically misses the cache rather than serving something
    stale.
  - Short default TTL (30s) bounds how stale a hit can ever be.
  - Only "ok" responses are cacheable. llm_error / safety_block /
    hallucination outcomes are never cached — a transient failure or a
    blocked/flagged response must always be retried, never repeated from
    cache.
  - Bounded size (LRU eviction) — never grows unbounded.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class CachedResponse:
    text: str
    status: str
    cached_at: float


_CACHEABLE_STATUSES = frozenset({"ok"})


class ResponseCache:
    def __init__(self, max_entries: int = 128, ttl_sec: float = 30.0) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl_sec = ttl_sec
        self._entries: OrderedDict[str, CachedResponse] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(question: str, context: str) -> str:
        raw = f"{question.strip().lower()}||{context}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, question: str, context: str, now: float | None = None) -> CachedResponse | None:
        now = now if now is not None else time.monotonic()
        key = self.make_key(question, context)
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
        self, question: str, context: str, text: str, status: str, now: float | None = None
    ) -> bool:
        """Returns True if stored, False if this status is not cacheable."""
        if status not in _CACHEABLE_STATUSES:
            return False
        now = now if now is not None else time.monotonic()
        key = self.make_key(question, context)
        self._entries[key] = CachedResponse(text=text, status=status, cached_at=now)
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

    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses, "hit_rate": self.hit_rate, "size": self.size}

    def clear(self) -> None:
        self._entries.clear()
