"""
bonbon_tts.core.metrics_collector
====================================
TTSMetricsCollector — operational metrics separate from health reporting.

Unlike ``TTSHealthTracker`` (which reports system health/availability),
``TTSMetricsCollector`` tracks throughput and usage statistics intended
for publishing to ``/bonbon/tts/metrics`` and operator dashboards.

Tracked metrics
---------------
- Synthesis count and error rate
- Cancellation count
- Emergency speech count
- Safety halt count (times the gate blocked speech)
- Queue overflow events
- Fallback activation count
- Total audio duration played (seconds)
- Rolling latency window → mean and p95
- Uptime since last reset
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass

from bonbon_tts.core.utterance_queue import Priority


@dataclass
class TTSMetrics:
    """Snapshot of operational TTS metrics."""

    synthesis_count: int = 0
    synthesis_errors: int = 0
    cancellations: int = 0
    emergency_count: int = 0
    safety_halts: int = 0
    queue_overflows: int = 0
    fallback_activations: int = 0
    total_audio_sec: float = 0.0
    mean_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    uptime_sec: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        d = self.to_dict()
        d["mean_latency_ms"] = round(d["mean_latency_ms"], 2)
        d["p95_latency_ms"] = round(d["p95_latency_ms"], 2)
        d["total_audio_sec"] = round(d["total_audio_sec"], 2)
        d["uptime_sec"] = round(d["uptime_sec"], 1)
        return json.dumps(d, separators=(",", ":"))


class TTSMetricsCollector:
    """
    Thread-safe operational metrics collector.

    Designed to be injected into :class:`~bonbon_tts.core.speech_synthesizer.SpeechSynthesizer`
    and read by the ROS2 node for periodic publishing.

    Parameters
    ----------
    window_size:
        Number of recent synthesis latencies to keep for statistics.
    """

    def __init__(self, window_size: int = 100) -> None:
        self._lock = threading.Lock()
        self._start_ts = time.monotonic()
        self._window_size = window_size
        self._latency_window: deque[float] = deque(maxlen=window_size)

        self._synthesis_count = 0
        self._synthesis_errors = 0
        self._cancellations = 0
        self._emergency_count = 0
        self._safety_halts = 0
        self._queue_overflows = 0
        self._fallback_activations = 0
        self._total_audio_sec = 0.0

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_synthesis(
        self,
        ms: float,
        success: bool,
        priority: Priority = Priority.NORMAL,
        is_fallback: bool = False,
    ) -> None:
        """Record one synthesis call."""
        with self._lock:
            self._synthesis_count += 1
            if success:
                self._latency_window.append(ms)
            else:
                self._synthesis_errors += 1
            if priority == Priority.EMERGENCY:
                self._emergency_count += 1
            if is_fallback:
                self._fallback_activations += 1

    def record_cancellation(self) -> None:
        """Record one speech cancellation event."""
        with self._lock:
            self._cancellations += 1

    def record_safety_halt(self) -> None:
        """Record one safety-gate block event."""
        with self._lock:
            self._safety_halts += 1

    def record_queue_overflow(self) -> None:
        """Record one queue overflow drop."""
        with self._lock:
            self._queue_overflows += 1

    def record_audio_played(self, duration_sec: float) -> None:
        """Accumulate played audio duration."""
        with self._lock:
            self._total_audio_sec += max(0.0, duration_sec)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def get_metrics(self) -> TTSMetrics:
        """Return a ``TTSMetrics`` snapshot (thread-safe)."""
        with self._lock:
            window = list(self._latency_window)
            snap = dict(
                synthesis_count=self._synthesis_count,
                synthesis_errors=self._synthesis_errors,
                cancellations=self._cancellations,
                emergency_count=self._emergency_count,
                safety_halts=self._safety_halts,
                queue_overflows=self._queue_overflows,
                fallback_activations=self._fallback_activations,
                total_audio_sec=self._total_audio_sec,
            )

        mean_ms = sum(window) / len(window) if window else 0.0
        p95_ms = self._percentile(window, 95)

        return TTSMetrics(
            **snap,
            mean_latency_ms=mean_ms,
            p95_latency_ms=p95_ms,
            uptime_sec=time.monotonic() - self._start_ts,
            timestamp=time.monotonic(),
        )

    def to_json(self) -> str:
        """Convenience wrapper: return metrics as a compact JSON string."""
        return self.get_metrics().to_json()

    # ── Management ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all counters (e.g. after a scheduled reporting window)."""
        with self._lock:
            self._latency_window.clear()
            self._synthesis_count = 0
            self._synthesis_errors = 0
            self._cancellations = 0
            self._emergency_count = 0
            self._safety_halts = 0
            self._queue_overflows = 0
            self._fallback_activations = 0
            self._total_audio_sec = 0.0
            self._start_ts = time.monotonic()

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _percentile(data: list, pct: float) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        k = (len(s) - 1) * pct / 100.0
        lo = int(k)
        hi = lo + 1
        if hi >= len(s):
            return s[-1]
        return s[lo] + (k - lo) * (s[hi] - s[lo])
