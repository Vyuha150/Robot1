"""Shared latency-measurement + budget-enforcement layer.

Every BonBon module needs the same thing: time a hot path, keep a rolling
window of samples, compute percentiles, and compare against a latency budget so
a regression trips a diagnostic. Before this module each benchmark
re-implemented percentile math; this is the single reusable implementation.

Pieces
------
* :class:`LatencyTracker` — rolling-window sample store with mean/p50/p95/p99.
* :class:`LatencyTimer`   — context manager / decorator that feeds a tracker.
* :class:`PerfBudget`     — a named target (e.g. behavior_decision ≤ 100 ms).
* :class:`BudgetReport`   — pass/fail of a tracker against its budget.

Pure Python, injectable clock → unit-testable with deterministic timings.
"""

from __future__ import annotations

import functools
import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional

_logger = logging.getLogger(__name__)

Clock = Callable[[], float]


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in [0,100]) of ``samples`` (seconds→same unit).

    Returns 0.0 for an empty list. Deterministic, dependency-free.
    """
    if not samples:
        return 0.0
    if pct <= 0:
        return min(samples)
    if pct >= 100:
        return max(samples)
    ordered = sorted(samples)
    # Nearest-rank method: rank = ceil(pct/100 * N), 1-indexed.
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass
class LatencyStats:
    """Summary of a window of latency samples (all values in milliseconds)."""

    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float


class LatencyTracker:
    """Rolling-window latency recorder with percentile queries.

    Args:
        name: Identifier (used in logs / reports).
        window: Number of most-recent samples to retain.
    """

    def __init__(self, name: str, window: int = 256) -> None:
        self.name = name
        self._samples: Deque[float] = deque(maxlen=max(1, window))
        self.total_count = 0

    def record_ms(self, value_ms: float) -> None:
        """Record one latency sample in milliseconds."""
        self._samples.append(float(value_ms))
        self.total_count += 1

    def record_s(self, value_s: float) -> None:
        """Record one latency sample given in seconds."""
        self.record_ms(value_s * 1000.0)

    def stats(self) -> LatencyStats:
        s = list(self._samples)
        if not s:
            return LatencyStats(0, 0, 0, 0, 0, 0, 0)
        return LatencyStats(
            count=len(s),
            mean_ms=sum(s) / len(s),
            p50_ms=percentile(s, 50),
            p95_ms=percentile(s, 95),
            p99_ms=percentile(s, 99),
            min_ms=min(s),
            max_ms=max(s),
        )

    def reset(self) -> None:
        self._samples.clear()


class LatencyTimer:
    """Context manager / decorator that records elapsed time into a tracker.

    Usage::

        tracker = LatencyTracker("behavior_decision")
        with LatencyTimer(tracker):
            decide()

        @LatencyTimer.wrap(tracker)
        def decide(): ...
    """

    def __init__(self, tracker: LatencyTracker, clock: Optional[Clock] = None) -> None:
        import time as _time
        self._tracker = tracker
        self._clock = clock or _time.perf_counter
        self._start = 0.0
        self.last_ms = 0.0

    def __enter__(self) -> "LatencyTimer":
        self._start = self._clock()
        return self

    def __exit__(self, *exc) -> bool:
        self.last_ms = (self._clock() - self._start) * 1000.0
        self._tracker.record_ms(self.last_ms)
        return False  # never suppress exceptions

    @classmethod
    def wrap(cls, tracker: LatencyTracker, clock: Optional[Clock] = None):
        """Decorator form: time every call of the wrapped function."""
        def deco(fn):
            @functools.wraps(fn)
            def inner(*a, **k):
                with cls(tracker, clock):
                    return fn(*a, **k)
            return inner
        return deco


@dataclass
class PerfBudget:
    """A named latency target.

    Attributes:
        name: Hot-path identifier (matches a LatencyTracker name).
        budget_ms: The target ceiling.
        metric: Which percentile to enforce ('p95' default, or 'p99'/'p50'/'max').
        critical: True when exceeding it is a safety-relevant regression.
    """

    name: str
    budget_ms: float
    metric: str = "p95"
    critical: bool = False


@dataclass
class BudgetReport:
    """Result of checking a tracker against a budget."""

    name: str
    budget_ms: float
    metric: str
    observed_ms: float
    passed: bool
    critical: bool
    samples: int


def check_budget(tracker: LatencyTracker, budget: PerfBudget) -> BudgetReport:
    """Compare a tracker's measured percentile against its budget."""
    st = tracker.stats()
    observed = {
        "p50": st.p50_ms, "p95": st.p95_ms, "p99": st.p99_ms,
        "max": st.max_ms, "mean": st.mean_ms,
    }.get(budget.metric, st.p95_ms)
    passed = st.count == 0 or observed <= budget.budget_ms
    if not passed:
        log = _logger.error if budget.critical else _logger.warning
        log("PERF BUDGET EXCEEDED: %s %s=%.1fms > %.1fms (n=%d)",
            budget.name, budget.metric, observed, budget.budget_ms, st.count)
    return BudgetReport(
        name=budget.name, budget_ms=budget.budget_ms, metric=budget.metric,
        observed_ms=round(observed, 3), passed=passed,
        critical=budget.critical, samples=st.count,
    )
