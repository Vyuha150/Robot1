"""InferenceMetricsCollector — rolling latency / timeout / error stats for a
runtime, cheap enough to update on every inference."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class MetricsSnapshot:
    total: int
    timeouts: int
    errors: int
    last_latency_ms: float
    mean_ms: float
    p95_ms: float
    fps: float


class InferenceMetricsCollector:
    def __init__(self, window: int = 100) -> None:
        self._lat: deque[float] = deque(maxlen=max(1, window))
        self._total = 0
        self._timeouts = 0
        self._errors = 0
        self._last_ms = 0.0

    def record(self, latency_ms: float, timed_out: bool = False, error: bool = False) -> None:
        self._total += 1
        self._last_ms = latency_ms
        if timed_out:
            self._timeouts += 1
        if error:
            self._errors += 1
        if not timed_out and not error:
            self._lat.append(latency_ms)

    def snapshot(self) -> MetricsSnapshot:
        if self._lat:
            ordered = sorted(self._lat)
            mean = sum(ordered) / len(ordered)
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            fps = 1000.0 / mean if mean > 0 else 0.0
        else:
            mean = p95 = fps = 0.0
        return MetricsSnapshot(
            total=self._total,
            timeouts=self._timeouts,
            errors=self._errors,
            last_latency_ms=self._last_ms,
            mean_ms=mean,
            p95_ms=p95,
            fps=fps,
        )

    @property
    def total(self) -> int:
        return self._total

    @property
    def timeouts(self) -> int:
        return self._timeouts

    @property
    def errors(self) -> int:
        return self._errors
