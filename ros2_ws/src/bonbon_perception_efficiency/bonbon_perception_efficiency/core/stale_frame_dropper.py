"""StaleFrameDropper — the one generic staleness check, reusable everywhere.

bonbon_multi_person_tracker and bonbon_object_intelligence each independently
reimplemented "is the upstream feed stale" as a local
``time.monotonic() - last_msg_time > timeout`` check
(``vision_stale_timeout_sec``). This is that exact check, factored out once,
so any current or future node can import it instead of rewriting it a third
time. It does not replace either package's existing check — both already
work and are tested — this is the shared primitive new consumers should use.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class StalenessResult:
    is_stale: bool
    age_sec: float


class StaleFrameDropper:
    def __init__(self, timeout_sec: float, clock: Callable[[], float] | None = None) -> None:
        self._timeout = timeout_sec
        self._clock = clock or time.monotonic
        self._last_seen: float | None = None

    def mark_received(self) -> None:
        """Call when a new message actually arrives."""
        self._last_seen = self._clock()

    def check(self) -> StalenessResult:
        """Call once per processing cycle to decide whether to drop."""
        if self._last_seen is None:
            return StalenessResult(is_stale=True, age_sec=float("inf"))
        age = self._clock() - self._last_seen
        return StalenessResult(is_stale=age > self._timeout, age_sec=age)
