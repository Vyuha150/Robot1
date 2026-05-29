"""
bonbon_gesture.health.health_monitor
======================================
Lightweight health-monitoring helper for the GestureNode.

Tracks:
* Frame processing rate (frames/sec)
* Backend processing latency (moving average)
* Consecutive backend failure count
* Total gestures published since startup
* Last backend error (if any)

The :meth:`build_status_dict` method returns a JSON-serialisable dict that is
published on the ``/bonbon/gesture/status`` topic and returned by the
``/bonbon/gesture/health_check`` service.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, List, Optional


class GestureHealthMonitor:
    """Accumulates health metrics for the GestureNode.

    Args:
        start_time: ``time.monotonic()`` timestamp at node start.  If omitted
            the current time is used.
        latency_window: Number of processing latency samples to keep for the
            rolling average.
    """

    def __init__(
        self,
        start_time: Optional[float] = None,
        latency_window: int = 30,
    ) -> None:
        self._start_time = start_time if start_time is not None else time.monotonic()
        self._latency_history: deque = deque(maxlen=latency_window)
        self._frames_received: int = 0
        self._frames_processed: int = 0
        self._gestures_published: int = 0
        self._consecutive_failures: int = 0
        self._last_error: Optional[str] = None
        self._backend_ready: bool = False
        self._enabled: bool = True
        self._warnings: List[str] = []

    # ------------------------------------------------------------------
    # Event recorders
    # ------------------------------------------------------------------

    def record_frame_received(self) -> None:
        """Increment the received-frame counter."""
        self._frames_received += 1

    def record_frame_processed(self, latency_sec: float) -> None:
        """Record a successfully processed frame.

        Args:
            latency_sec: Wall-clock time taken by the backend for this frame.
        """
        self._frames_processed += 1
        self._consecutive_failures = 0
        self._latency_history.append(latency_sec)

    def record_backend_failure(self, error: str) -> None:
        """Record a backend processing failure.

        Args:
            error: Human-readable error description.
        """
        self._consecutive_failures += 1
        self._last_error = error

    def record_gesture_published(self) -> None:
        """Increment the published-gesture counter."""
        self._gestures_published += 1

    def set_backend_ready(self, ready: bool) -> None:
        """Update the backend readiness flag.

        Args:
            ready: True when the backend has warmed up successfully.
        """
        self._backend_ready = ready

    def set_enabled(self, enabled: bool) -> None:
        """Update the enabled flag.

        Args:
            enabled: Current value of the gesture-processing enable flag.
        """
        self._enabled = enabled

    # ------------------------------------------------------------------
    # Health assessment
    # ------------------------------------------------------------------

    @property
    def is_healthy(self) -> bool:
        """True when no critical fault conditions are active."""
        return (
            self._backend_ready
            and self._enabled
            and self._consecutive_failures < 5
        )

    @property
    def warnings(self) -> List[str]:
        """List of current warning strings."""
        w: List[str] = []
        if self._consecutive_failures >= 3:
            w.append(f"consecutive_backend_failures={self._consecutive_failures}")
        if self._last_error is not None and self._consecutive_failures > 0:
            w.append(f"last_error={self._last_error}")
        if not self._enabled:
            w.append("gesture_processing_disabled")
        return w

    @property
    def errors(self) -> List[str]:
        """List of current error strings (critical conditions)."""
        e: List[str] = []
        if not self._backend_ready:
            e.append("backend_not_ready")
        if self._consecutive_failures >= 5:
            e.append(f"too_many_failures={self._consecutive_failures}")
        return e

    def uptime_sec(self) -> float:
        """Seconds since the node started.

        Returns:
            Elapsed seconds as a float.
        """
        return time.monotonic() - self._start_time

    def avg_latency_ms(self) -> float:
        """Rolling average backend latency in milliseconds.

        Returns:
            Average latency in ms, or 0.0 when no samples have been recorded.
        """
        if not self._latency_history:
            return 0.0
        return sum(self._latency_history) / len(self._latency_history) * 1000.0

    # ------------------------------------------------------------------
    # Status serialisation
    # ------------------------------------------------------------------

    def build_status_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable health status dictionary.

        Returns:
            Dictionary with keys: ``healthy``, ``uptime_sec``,
            ``frames_received``, ``frames_processed``, ``gestures_published``,
            ``avg_latency_ms``, ``consecutive_failures``, ``backend_ready``,
            ``enabled``, ``warnings``, ``errors``, ``last_error``.
        """
        return {
            "healthy": self.is_healthy,
            "uptime_sec": round(self.uptime_sec(), 2),
            "frames_received": self._frames_received,
            "frames_processed": self._frames_processed,
            "gestures_published": self._gestures_published,
            "avg_latency_ms": round(self.avg_latency_ms(), 2),
            "consecutive_failures": self._consecutive_failures,
            "backend_ready": self._backend_ready,
            "enabled": self._enabled,
            "warnings": self.warnings,
            "errors": self.errors,
            "last_error": self._last_error,
        }
