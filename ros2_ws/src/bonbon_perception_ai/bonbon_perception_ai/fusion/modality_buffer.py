"""
bonbon_perception_ai.fusion.modality_buffer
============================================
Thread-safe, timestamped buffer for one input modality.

Each modality (objects, persons, speech, pose, nav) has its own buffer.
Buffers are updated by ROS2 subscription callbacks and read by the fusion loop.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class ModalityBuffer:
    """
    Thread-safe single-slot store with age / staleness tracking.

    Parameters
    ----------
    name :
        Human-readable modality name used in logs and stale-modality lists.
    stale_timeout_sec :
        A reading older than this is considered stale. A buffer that has
        never been written is always stale.
    """

    def __init__(self, name: str, stale_timeout_sec: float) -> None:
        if stale_timeout_sec <= 0:
            raise ValueError(f"ModalityBuffer '{name}': stale_timeout_sec must be > 0")
        self.name = name
        self.stale_timeout_sec = stale_timeout_sec
        self._data: Any = None
        self._timestamp: float = 0.0  # 0 = never written
        self._update_count: int = 0
        self._lock = threading.Lock()

    # ── Write ─────────────────────────────────────────────────────────────────

    def update(self, data: Any) -> None:
        """Store a new reading; thread-safe."""
        with self._lock:
            self._data = data
            self._timestamp = time.monotonic()
            self._update_count += 1

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self) -> tuple[Any | None, float]:
        """Return (data, timestamp).  data is None if never written."""
        with self._lock:
            return self._data, self._timestamp

    def peek(self) -> Any | None:
        """Return latest data without the timestamp."""
        with self._lock:
            return self._data

    # ── Staleness ─────────────────────────────────────────────────────────────

    def is_stale(self) -> bool:
        """True when buffer is empty or the last update is too old."""
        with self._lock:
            if self._timestamp == 0.0:
                return True
            return (time.monotonic() - self._timestamp) > self.stale_timeout_sec

    def age_sec(self) -> float:
        """Seconds since last update. Returns inf if never written."""
        with self._lock:
            if self._timestamp == 0.0:
                return float("inf")
            return time.monotonic() - self._timestamp

    # ── Housekeeping ──────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Discard stored data (e.g. on node deactivate / privacy flush)."""
        with self._lock:
            self._data = None
            self._timestamp = 0.0

    @property
    def update_count(self) -> int:
        """Total number of writes since construction (not reset by clear)."""
        with self._lock:
            return self._update_count

    def __repr__(self) -> str:
        stale = "STALE" if self.is_stale() else f"age={self.age_sec():.2f}s"
        return f"ModalityBuffer({self.name!r} {stale} updates={self.update_count})"
