"""
bonbon_tts.core.utterance_queue
=================================
Priority-based utterance queue with deduplication, staleness eviction,
and thread-safe access.

Priority ordering (lower value = higher priority)
-------------------------------------------------
  EMERGENCY = 0  — immediate interrupt; path-clearing safety alerts
  HIGH      = 1  — navigation status, urgent responses
  NORMAL    = 2  — conversational replies
  LOW       = 3  — background status, non-urgent info

Deduplication
-------------
If ``dedup_key`` is set on an utterance, any previously queued utterance
with the same key is silently replaced.  Useful for status updates that
supersede earlier ones (e.g., repeated battery percentage announcements).

Overflow
--------
When the queue is full, the lowest-priority item is dropped.  If all
items share the same priority, the oldest is dropped.
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


# ── Priority ──────────────────────────────────────────────────────────────────


class Priority(IntEnum):
    """
    Utterance priority levels.  Lower value = higher priority.

    Canonical names (preferred in new code)
    ----------------------------------------
    EMERGENCY               = 0  Robot safety-critical interrupts.
    SAFETY_WARNING          = 1  Warnings from the Safety Supervisor.
    USER_RESPONSE           = 2  Direct conversational replies.
    FILLER                  = 3  Bridging clips ("one moment…").
    BACKGROUND_NOTIFICATION = 4  Non-urgent status updates.

    Backward-compatible aliases (same integer values)
    --------------------------------------------------
    HIGH   = 1   alias for SAFETY_WARNING
    NORMAL = 2   alias for USER_RESPONSE
    LOW    = 3   alias for FILLER
    """

    EMERGENCY = 0
    SAFETY_WARNING = 1
    HIGH = 1  # backward-compat alias
    USER_RESPONSE = 2
    NORMAL = 2  # backward-compat alias
    FILLER = 3
    LOW = 3  # backward-compat alias
    BACKGROUND_NOTIFICATION = 4


# ── Utterance ─────────────────────────────────────────────────────────────────


@dataclass
class Utterance:
    """
    A single item of speech to be synthesised and played.

    Parameters
    ----------
    text:
        Plain text to speak.
    priority:
        Playback priority (EMERGENCY = highest).
    source:
        Human-readable origin tag for debugging (e.g. "navigation",
        "llm_response").
    utterance_id:
        Unique identifier auto-generated if not supplied.
    max_age_sec:
        Seconds after which this utterance is silently dropped from the queue
        if still unplayed.  0.0 means never expire.
    dedup_key:
        When non-empty, a newly queued utterance replaces any existing
        queued utterance with the same key.
    interrupt:
        When True the synthesizer immediately stops current speech and plays
        this utterance next.  Automatically True for EMERGENCY priority.
    """

    text: str
    priority: Priority = Priority.NORMAL
    source: str = ""
    utterance_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enqueue_ts: float = field(default_factory=time.monotonic)
    max_age_sec: float = 30.0
    dedup_key: str = ""
    interrupt: bool = False

    def is_stale(self) -> bool:
        """Return True if this utterance should be dropped without playing."""
        if self.max_age_sec <= 0:
            return False
        return (time.monotonic() - self.enqueue_ts) > self.max_age_sec

    # heapq ordering: sort by (priority, enqueue_ts) so same-priority
    # items are played FIFO.
    def __lt__(self, other: Utterance) -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.enqueue_ts < other.enqueue_ts

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Utterance):
            return NotImplemented
        return self.utterance_id == other.utterance_id


# ── Queue ─────────────────────────────────────────────────────────────────────


class UtteranceQueue:
    """
    Thread-safe priority queue for TTS utterances.

    Usage::

        q = UtteranceQueue(cfg)
        interrupt_needed = q.enqueue(Utterance(text="Hello", priority=Priority.NORMAL))
        utt = q.dequeue()   # returns highest-priority non-stale item
    """

    def __init__(self, max_depth: int = 32, dedup_enabled: bool = True) -> None:
        self._max_depth = max_depth
        self._dedup = dedup_enabled
        self._heap: list[Utterance] = []
        self._dedup_index: dict[str, str] = {}  # dedup_key → utterance_id
        self._lock = threading.Lock()
        self._overflow_count = 0

    # ── Enqueue ────────────────────────────────────────────────────────────────

    def enqueue(self, utt: Utterance) -> bool:
        """
        Add an utterance to the queue.

        Returns
        -------
        bool
            True if the caller should interrupt current speech immediately
            (i.e. the utterance has ``interrupt=True`` or is EMERGENCY).
        """
        # EMERGENCY always sets interrupt flag
        if utt.priority == Priority.EMERGENCY:
            utt.interrupt = True

        with self._lock:
            # Deduplication: remove previous utterance with same key
            if self._dedup and utt.dedup_key:
                old_id = self._dedup_index.get(utt.dedup_key)
                if old_id is not None:
                    self._heap = [u for u in self._heap if u.utterance_id != old_id]
                    heapq.heapify(self._heap)
                    logger.debug("Queue: replaced utterance with dedup_key=%r", utt.dedup_key)
                self._dedup_index[utt.dedup_key] = utt.utterance_id

            # Overflow: drop lowest-priority / oldest if queue is full
            if len(self._heap) >= self._max_depth:
                self._drop_lowest_priority()
                self._overflow_count += 1

            heapq.heappush(self._heap, utt)
            logger.debug(
                "Queue: enqueued id=%s prio=%s depth=%d src=%r",
                utt.utterance_id,
                utt.priority.name,
                len(self._heap),
                utt.source,
            )

        return utt.interrupt

    # ── Dequeue ────────────────────────────────────────────────────────────────

    def dequeue(self) -> Utterance | None:
        """
        Pop and return the highest-priority non-stale utterance.

        Stale utterances are silently discarded.
        Returns None if the queue is empty.
        """
        with self._lock:
            while self._heap:
                utt = heapq.heappop(self._heap)
                # Clean up dedup index
                if utt.dedup_key and self._dedup_index.get(utt.dedup_key) == utt.utterance_id:
                    del self._dedup_index[utt.dedup_key]
                if utt.is_stale():
                    logger.debug("Queue: dropped stale utterance id=%s", utt.utterance_id)
                    continue
                return utt
        return None

    # ── Peek ──────────────────────────────────────────────────────────────────

    def peek_priority(self) -> Priority | None:
        """Return the priority of the next utterance without removing it."""
        with self._lock:
            if self._heap:
                return self._heap[0].priority
        return None

    # ── Bulk operations ────────────────────────────────────────────────────────

    def clear(self) -> int:
        """Remove all utterances.  Returns the count of dropped items."""
        with self._lock:
            count = len(self._heap)
            self._heap.clear()
            self._dedup_index.clear()
            return count

    def clear_below_priority(self, min_priority: Priority) -> int:
        """Drop all utterances with priority strictly lower (higher number) than min_priority."""
        with self._lock:
            before = len(self._heap)
            self._heap = [u for u in self._heap if u.priority <= min_priority]
            heapq.heapify(self._heap)
            dropped = before - len(self._heap)
            if dropped:
                logger.debug("Queue: dropped %d low-priority utterances", dropped)
            return dropped

    # ── Properties ────────────────────────────────────────────────────────────

    def depth(self) -> int:
        """Current number of queued utterances."""
        with self._lock:
            return len(self._heap)

    @property
    def overflow_count(self) -> int:
        """Total number of utterances dropped due to queue overflow."""
        return self._overflow_count

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._heap) == 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _drop_lowest_priority(self) -> None:
        """Drop the lowest-priority (or oldest same-priority) utterance."""
        if not self._heap:
            return
        # Find the item with the worst priority, breaking ties by oldest first
        worst_idx = max(
            range(len(self._heap)),
            key=lambda i: (self._heap[i].priority, -self._heap[i].enqueue_ts),
        )
        dropped = self._heap.pop(worst_idx)
        heapq.heapify(self._heap)
        if dropped.dedup_key and self._dedup_index.get(dropped.dedup_key) == dropped.utterance_id:
            del self._dedup_index[dropped.dedup_key]
        logger.warning(
            "Queue: overflow — dropped id=%s prio=%s text=%r",
            dropped.utterance_id,
            dropped.priority.name,
            dropped.text[:40],
        )
