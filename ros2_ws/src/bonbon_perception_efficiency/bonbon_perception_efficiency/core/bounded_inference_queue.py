"""BoundedInferenceQueue — the fix for a real audit finding.

affective_ai_node submits inference work to a ThreadPoolExecutor from every
audio/image callback with no backpressure check (audit finding: unbounded
queue growth under sustained input). gesture_node avoids this by checking
``in_flight`` before submitting — but that pattern only tracks ONE in-flight
task; it can't express "allow up to N concurrent, drop the rest."

This is that pattern generalised: a small bounded queue that callers check
BEFORE submitting to their own executor. It never runs inference itself
(no new pipeline) — it's a backpressure gate a node's existing dispatch
code wraps around its existing ThreadPoolExecutor.submit() call.

Drop policy is "drop newest" by default (reject the incoming item when full)
— for real-time perception, an item that can't be processed promptly is
generally less useful than completing what's already in flight, and
"drop oldest" would mean discarding work already paid for.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class QueueAdmitResult:
    admitted: bool
    queue_depth: int
    dropped_count: int


class BoundedInferenceQueue:
    def __init__(
        self,
        max_depth: int,
        drop_oldest: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._max_depth = max(1, max_depth)
        self._drop_oldest = drop_oldest
        self._clock = clock or time.monotonic
        self._items: deque = deque()
        self._dropped_count = 0

    def try_admit(self, token: object = None) -> QueueAdmitResult:
        """Call before dispatching work. Returns admitted=False if the queue
        is full — the caller must NOT submit to its executor in that case."""
        if len(self._items) >= self._max_depth:
            if self._drop_oldest and self._items:
                self._items.popleft()
            else:
                self._dropped_count += 1
                return QueueAdmitResult(
                    admitted=False, queue_depth=len(self._items), dropped_count=self._dropped_count
                )
        self._items.append((token, self._clock()))
        return QueueAdmitResult(
            admitted=True, queue_depth=len(self._items), dropped_count=self._dropped_count
        )

    def mark_complete(self, token: object = None) -> None:
        """Call when a dispatched item finishes, freeing a queue slot."""
        if not self._items:
            return
        if token is None:
            self._items.popleft()
            return
        for i, (t, _) in enumerate(self._items):
            if t == token:
                del self._items[i]
                return
        # Token not found — pop oldest as a safe fallback rather than leak a slot.
        self._items.popleft()

    @property
    def depth(self) -> int:
        return len(self._items)

    @property
    def is_full(self) -> bool:
        return len(self._items) >= self._max_depth

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def oldest_age_sec(self) -> float:
        if not self._items:
            return 0.0
        return self._clock() - self._items[0][1]
