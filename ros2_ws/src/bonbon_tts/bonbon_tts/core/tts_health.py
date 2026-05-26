"""
bonbon_tts.core.tts_health
============================
Health tracking and reporting for the TTS subsystem.

Tracks synthesis latency, error rates, fallback usage, and playback
statistics.  All state is updated from the worker thread; ``get_report``
is safe to call from any thread (takes a lock).

Typical usage
-------------
::

    tracker = TTSHealthTracker()
    tracker.record_synthesis(latency_ms=120.0, success=True)
    tracker.record_play(duration_sec=2.5)
    report = tracker.get_report(
        queue_depth=3,
        backend="piper",
        synth_ok=True,
        speaker_ok=True,
    )
    if not report.is_healthy:
        logger.warning("TTS health degraded: %s", report.summary())
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


# ── Health report ─────────────────────────────────────────────────────────────

@dataclass
class TTSHealthReport:
    """
    Snapshot of TTS subsystem health.

    All ``*_ms`` fields are in milliseconds.  ``timestamp`` is
    ``time.monotonic()`` at report generation time.
    """

    synthesizer_ok:     bool
    speaker_ok:         bool
    backend:            str
    queue_depth:        int
    queue_overflows:    int

    # Latency statistics (milliseconds)
    last_synthesis_ms:  float
    mean_synthesis_ms:  float
    p95_synthesis_ms:   float   # 95th-percentile over the rolling window

    # Error / degradation counters
    synthesis_errors:   int
    fallback_count:     int

    # Throughput
    utterances_played:  int
    total_audio_sec:    float

    # Uptime
    uptime_sec:         float
    timestamp:          float

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def is_healthy(self) -> bool:
        """
        True when the system is fully operational.

        Criteria:
        - synthesizer up
        - speaker up
        - error rate < 50 % of recent calls (crude check: errors < utterances)
        """
        return (
            self.synthesizer_ok
            and self.speaker_ok
            and self.synthesis_errors <= max(1, self.utterances_played)
        )

    @property
    def is_degraded(self) -> bool:
        """True when running on fallback backend."""
        return self.fallback_count > 0 and not self.is_healthy

    def summary(self) -> str:
        """One-line human-readable summary for logging."""
        status = "OK" if self.is_healthy else ("DEGRADED" if self.synthesizer_ok else "DOWN")
        return (
            f"TTS {status} | backend={self.backend} "
            f"queue={self.queue_depth} errors={self.synthesis_errors} "
            f"fallback={self.fallback_count} "
            f"latency_mean={self.mean_synthesis_ms:.0f}ms "
            f"p95={self.p95_synthesis_ms:.0f}ms "
            f"played={self.utterances_played}"
        )


# ── Health tracker ────────────────────────────────────────────────────────────

class TTSHealthTracker:
    """
    Collects runtime metrics for the TTS pipeline.

    Thread-safe — all mutating methods acquire ``_lock``.

    Parameters
    ----------
    window_size:
        Number of recent synthesis calls to keep for latency statistics.
        Defaults to 50.
    """

    def __init__(self, window_size: int = 50) -> None:
        self._lock              = threading.Lock()
        self._start_ts          = time.monotonic()
        self._window_size       = window_size

        # Rolling latency window
        self._latency_window:   Deque[float] = deque(maxlen=window_size)

        # Counters
        self._synthesis_errors  = 0
        self._fallback_count    = 0
        self._utterances_played = 0
        self._queue_overflows   = 0
        self._total_audio_sec   = 0.0

        # Last observed latency
        self._last_ms           = 0.0

    # ── Mutation helpers ──────────────────────────────────────────────────────

    def record_synthesis(
        self,
        ms: float,
        success: bool,
        fallback: bool = False,
    ) -> None:
        """
        Record one synthesis call.

        Parameters
        ----------
        ms:
            Wall-clock latency of the synthesis call in milliseconds.
        success:
            False if the synthesis raised TTSError.
        fallback:
            True if the output was produced by the fallback backend.
        """
        with self._lock:
            self._last_ms = ms
            if success:
                self._latency_window.append(ms)
            else:
                self._synthesis_errors += 1
            if fallback:
                self._fallback_count += 1

    def record_play(self, duration_sec: float) -> None:
        """Record one successfully played utterance."""
        with self._lock:
            self._utterances_played += 1
            self._total_audio_sec   += duration_sec

    def record_queue_overflow(self) -> None:
        """Record one queue overflow event."""
        with self._lock:
            self._queue_overflows += 1

    # ── Report generation ─────────────────────────────────────────────────────

    def get_report(
        self,
        queue_depth:  int,
        backend:      str,
        synth_ok:     bool,
        speaker_ok:   bool,
    ) -> TTSHealthReport:
        """
        Build and return a ``TTSHealthReport`` snapshot.

        Parameters
        ----------
        queue_depth:
            Current number of items in the utterance queue.
        backend:
            Name of the active TTS backend (e.g. "piper" or "mock").
        synth_ok:
            True if the synthesizer worker is running.
        speaker_ok:
            True if the speaker bridge reports as healthy.
        """
        with self._lock:
            window  = list(self._latency_window)
            last_ms = self._last_ms
            errors  = self._synthesis_errors
            falls   = self._fallback_count
            played  = self._utterances_played
            oflows  = self._queue_overflows
            total_a = self._total_audio_sec

        mean_ms = (sum(window) / len(window)) if window else 0.0
        p95_ms  = self._percentile(window, 95) if window else 0.0
        uptime  = time.monotonic() - self._start_ts

        return TTSHealthReport(
            synthesizer_ok    = synth_ok,
            speaker_ok        = speaker_ok,
            backend           = backend,
            queue_depth       = queue_depth,
            queue_overflows   = oflows,
            last_synthesis_ms = last_ms,
            mean_synthesis_ms = mean_ms,
            p95_synthesis_ms  = p95_ms,
            synthesis_errors  = errors,
            fallback_count    = falls,
            utterances_played = played,
            total_audio_sec   = total_a,
            uptime_sec        = uptime,
            timestamp         = time.monotonic(),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _percentile(data: list, pct: float) -> float:
        """Return the *pct*-th percentile of *data* (linear interpolation)."""
        if not data:
            return 0.0
        s = sorted(data)
        k = (len(s) - 1) * pct / 100.0
        lo = int(k)
        hi = lo + 1
        if hi >= len(s):
            return s[-1]
        return s[lo] + (k - lo) * (s[hi] - s[lo])

    def reset(self) -> None:
        """Reset all counters (useful for tests)."""
        with self._lock:
            self._latency_window.clear()
            self._synthesis_errors  = 0
            self._fallback_count    = 0
            self._utterances_played = 0
            self._queue_overflows   = 0
            self._total_audio_sec   = 0.0
            self._last_ms           = 0.0
            self._start_ts          = time.monotonic()
