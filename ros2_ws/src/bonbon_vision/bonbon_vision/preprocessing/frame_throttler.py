"""
bonbon_vision.preprocessing.frame_throttler
=============================================
Token-bucket frame-rate limiter.

The camera HAL node may publish at 30 Hz while detection only needs 10 Hz.
FrameThrottler decides whether a newly arrived frame should be processed
or dropped, maintaining a configurable target rate without busy-waiting.

Design
------
Uses a simple token-bucket where one token is released every
1/target_hz seconds.  If a token is available when should_process() is
called it is consumed and True is returned; otherwise False (drop frame).

Thread safety: the token is a float timestamp — all access via a
threading.Lock.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class FrameThrottler:
    """
    Token-bucket frame-rate limiter.

    Parameters
    ----------
    target_hz  float  desired processing rate (frames per second)
    burst      int    maximum burst size in tokens (default 1 = no burst)
    """

    def __init__(self, target_hz: float, burst: int = 1) -> None:
        if target_hz <= 0:
            raise ValueError(f"target_hz must be > 0, got {target_hz}")
        self._interval = 1.0 / target_hz
        self._burst = max(1, burst)
        self._tokens: float = float(self._burst)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

        # Metrics
        self._total_offered: int = 0
        self._total_processed: int = 0
        self._total_dropped: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def should_process(self) -> bool:
        """
        Return True if this frame should be processed; False = drop.
        Thread-safe.
        """
        with self._lock:
            self._refill()
            self._total_offered += 1
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._total_processed += 1
                return True
            self._total_dropped += 1
            return False

    def set_rate(self, target_hz: float) -> None:
        """Update target rate at runtime (e.g., from ROS2 param change)."""
        if target_hz <= 0:
            raise ValueError(f"target_hz must be > 0, got {target_hz}")
        with self._lock:
            self._interval = 1.0 / target_hz
            # Reset tokens to avoid burst after rate decrease
            self._tokens = min(self._tokens, 1.0)
        logger.info("stage=throttler event=rate_updated target_hz=%.1f", target_hz)

    @property
    def drop_rate(self) -> float:
        """Fraction of offered frames that were dropped (0.0–1.0)."""
        with self._lock:
            if self._total_offered == 0:
                return 0.0
            return self._total_dropped / self._total_offered

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "offered": self._total_offered,
                "processed": self._total_processed,
                "dropped": self._total_dropped,
                "drop_rate": self.drop_rate,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._total_offered = 0
            self._total_processed = 0
            self._total_dropped = 0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refill(self) -> None:
        """Add tokens proportional to elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed / self._interval
        if new_tokens > 0:
            self._tokens = min(float(self._burst), self._tokens + new_tokens)
            self._last_refill = now
