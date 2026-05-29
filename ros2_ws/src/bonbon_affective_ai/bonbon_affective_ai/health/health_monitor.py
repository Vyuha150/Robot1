"""Health monitor tracking backend liveness and recent error history."""

from __future__ import annotations

import time
from typing import List


class AffectiveAIHealthMonitor:
    """Tracks per-backend health state and recent error messages.

    Provides a ``get_status()`` snapshot used by the health-check service and
    the ``/bonbon/affective/status`` publisher.  All methods are designed to be
    called from a single thread; external locking is the caller's
    responsibility if multi-threaded access is needed.
    """

    def __init__(self) -> None:
        """Initialise with all backends marked as not-yet-confirmed healthy."""
        self._start_time: float = time.time()
        self._face_ok: bool = False
        self._voice_ok: bool = False
        self._text_ok: bool = True  # rule-based text analysis always works
        self._last_face_time: float = 0.0
        self._last_voice_time: float = 0.0
        self._last_text_time: float = 0.0
        self._errors: List[str] = []

    # ── Face backend events ───────────────────────────────────────────────────

    def record_face_success(self) -> None:
        """Mark the face backend as healthy and update the last-seen timestamp."""
        self._face_ok = True
        self._last_face_time = time.time()

    def record_face_failure(self, err: str) -> None:
        """Record a face backend failure.

        Args:
            err: Short error description to append to the error log.
        """
        self._errors.append(f"face:{err}")
        self._face_ok = False

    # ── Voice backend events ──────────────────────────────────────────────────

    def record_voice_success(self) -> None:
        """Mark the voice backend as healthy and update the last-seen timestamp."""
        self._voice_ok = True
        self._last_voice_time = time.time()

    def record_voice_failure(self, err: str) -> None:
        """Record a voice backend failure.

        Args:
            err: Short error description to append to the error log.
        """
        self._errors.append(f"voice:{err}")
        self._voice_ok = False

    # ── Text backend events ───────────────────────────────────────────────────

    def record_text_success(self) -> None:
        """Mark the text backend as healthy and update the last-seen timestamp."""
        self._text_ok = True
        self._last_text_time = time.time()

    def record_text_failure(self, err: str) -> None:
        """Record a text backend failure.

        Args:
            err: Short error description to append to the error log.
        """
        self._errors.append(f"text:{err}")
        # Text backend can recover; we still mark failure for visibility.
        self._text_ok = False

    # ── Status snapshot ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a status snapshot dictionary.

        Returns:
            dict: Contains the following keys:
                - ``face_backend_ok`` (bool)
                - ``voice_backend_ok`` (bool)
                - ``text_backend_ok`` (bool)
                - ``recent_errors`` (list[str]): Last 5 error messages.
                - ``last_face_analysis_ago_sec`` (float)
                - ``last_voice_analysis_ago_sec`` (float)
                - ``last_text_analysis_ago_sec`` (float)
                - ``uptime_sec`` (float)
        """
        now = time.time()
        return {
            "face_backend_ok": self._face_ok,
            "voice_backend_ok": self._voice_ok,
            "text_backend_ok": self._text_ok,
            "recent_errors": self._errors[-5:],
            "last_face_analysis_ago_sec": now - self._last_face_time,
            "last_voice_analysis_ago_sec": now - self._last_voice_time,
            "last_text_analysis_ago_sec": now - self._last_text_time,
            "uptime_sec": now - self._start_time,
        }

    def is_healthy(self) -> bool:
        """Return True if at least the text backend is operational.

        Face and voice backends are optional (may be unavailable if ML
        dependencies are not installed).

        Returns:
            bool: True if the system can perform at least minimal analysis.
        """
        return self._text_ok

    @property
    def uptime_sec(self) -> float:
        """Return the number of seconds since the monitor was created."""
        return time.time() - self._start_time

    def clear_errors(self) -> None:
        """Flush the accumulated error log."""
        self._errors.clear()
