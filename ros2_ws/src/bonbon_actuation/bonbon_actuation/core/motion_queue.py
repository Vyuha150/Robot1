"""MotionQueue — priority-ordered queue of pending gesture requests.

The actuation node executes one gesture at a time. Incoming requests that
arrive while a gesture is running are queued here rather than dropped, so that
expressive motions (wave, nod, point …) are serialised cleanly instead of
racing each other on the servo bus.

Ordering rules
--------------
1. Higher ``priority`` is served first (20=emergency … 0=low).
2. Within equal priority, FIFO by arrival sequence.
3. The queue is bounded; when full, the lowest-priority / oldest entry is
   evicted so that a fresh high-priority request is never lost.

Preemption
----------
``should_preempt(running_priority)`` lets the node decide whether the head of
the queue should interrupt the gesture currently executing. Emergency-class
requests (priority >= ``preempt_threshold``) always preempt.

This module contains **no ROS2 dependency** so it is unit-testable in
isolation and reusable from both the node and tests.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional

_logger = logging.getLogger(__name__)

# Priority at/above which a queued request preempts the running gesture.
DEFAULT_PREEMPT_THRESHOLD = 10
# Default maximum number of queued (not-yet-running) requests.
DEFAULT_MAX_DEPTH = 16


@dataclass(order=True)
class _QueueEntry:
    """Internal heap entry. ``sort_key`` drives the heap ordering."""

    sort_key: tuple = field(compare=True)
    seq: int = field(compare=False, default=0)
    gesture_name: str = field(compare=False, default="")
    priority: int = field(compare=False, default=0)
    speed_scale: float = field(compare=False, default=1.0)
    event_id: str = field(compare=False, default="")
    interruptible: bool = field(compare=False, default=True)


@dataclass
class QueuedGesture:
    """Public view of a dequeued gesture request."""

    gesture_name: str
    priority: int
    speed_scale: float
    event_id: str
    interruptible: bool


class MotionQueue:
    """Thread-safe priority queue for gesture requests.

    Args:
        max_depth: Maximum number of pending requests. When exceeded, the
            lowest-priority entry is evicted.
        preempt_threshold: Priority at/above which the head of the queue should
            interrupt a running gesture.
    """

    def __init__(
        self,
        max_depth: int = DEFAULT_MAX_DEPTH,
        preempt_threshold: int = DEFAULT_PREEMPT_THRESHOLD,
    ) -> None:
        self._max_depth = max(1, max_depth)
        self._preempt_threshold = preempt_threshold
        self._heap: List[_QueueEntry] = []
        self._counter = itertools.count()
        self._lock = threading.Lock()
        # Telemetry counters
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.total_evicted = 0

    # ── Mutation ────────────────────────────────────────────────────────────

    def enqueue(
        self,
        gesture_name: str,
        priority: int,
        speed_scale: float = 1.0,
        event_id: str = "",
        interruptible: bool = True,
    ) -> bool:
        """Add a request to the queue.

        Returns:
            ``True`` if the request was queued, ``False`` if it was rejected
            (which only happens when it is itself the lowest-priority entry in
            an already-full queue).
        """
        with self._lock:
            seq = next(self._counter)
            # Negative priority → higher priority sorts first in a min-heap.
            # Tie-break by sequence so equal priorities are FIFO.
            entry = _QueueEntry(
                sort_key=(-int(priority), seq),
                seq=seq,
                gesture_name=gesture_name,
                priority=int(priority),
                speed_scale=float(speed_scale),
                event_id=event_id,
                interruptible=interruptible,
            )
            heapq.heappush(self._heap, entry)
            self.total_enqueued += 1

            if len(self._heap) > self._max_depth:
                # Evict the worst entry (lowest priority, then oldest).
                evicted = self._evict_worst_locked()
                if evicted is entry:
                    _logger.warning(
                        "MotionQueue full (%d): request '%s' (prio=%d) rejected.",
                        self._max_depth, gesture_name, priority,
                    )
                    return False
                _logger.warning(
                    "MotionQueue full (%d): evicted '%s' (prio=%d) to admit '%s'.",
                    self._max_depth, evicted.gesture_name, evicted.priority,
                    gesture_name,
                )
            return True

    def dequeue(self) -> Optional[QueuedGesture]:
        """Pop and return the highest-priority request, or ``None`` if empty."""
        with self._lock:
            if not self._heap:
                return None
            entry = heapq.heappop(self._heap)
            self.total_dequeued += 1
            return QueuedGesture(
                gesture_name=entry.gesture_name,
                priority=entry.priority,
                speed_scale=entry.speed_scale,
                event_id=entry.event_id,
                interruptible=entry.interruptible,
            )

    def clear(self) -> int:
        """Discard all pending requests. Returns the count discarded."""
        with self._lock:
            n = len(self._heap)
            self._heap.clear()
            return n

    # ── Inspection ──────────────────────────────────────────────────────────

    def peek_priority(self) -> Optional[int]:
        """Return the priority of the head request without removing it."""
        with self._lock:
            if not self._heap:
                return None
            return self._heap[0].priority

    def should_preempt(self, running_priority: int) -> bool:
        """Return ``True`` if the head request should interrupt the running gesture.

        A queued request preempts when it is emergency-class (>= threshold) or
        strictly higher priority than the gesture currently running.
        """
        head = self.peek_priority()
        if head is None:
            return False
        if head >= self._preempt_threshold:
            return True
        return head > running_priority

    def depth(self) -> int:
        with self._lock:
            return len(self._heap)

    def is_empty(self) -> bool:
        return self.depth() == 0

    # ── Internals ─────────────────────────────────────────────────────────────

    def _evict_worst_locked(self) -> _QueueEntry:
        """Remove and return the lowest-priority (then oldest) entry.

        Caller must hold ``self._lock``.
        """
        # Worst entry = lowest priority value, then oldest (largest seq).
        worst_idx = min(
            range(len(self._heap)),
            key=lambda i: (self._heap[i].priority, -self._heap[i].seq),
        )
        worst = self._heap[worst_idx]
        self._heap[worst_idx] = self._heap[-1]
        self._heap.pop()
        if self._heap:
            heapq.heapify(self._heap)
        self.total_evicted += 1
        return worst
