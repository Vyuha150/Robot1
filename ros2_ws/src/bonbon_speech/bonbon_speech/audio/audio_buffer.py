"""
bonbon_speech.audio.audio_buffer
=================================
Thread-safe rolling audio ring-buffer with prebuffer support.

Design
------
* Stores raw float32 samples from the HAL AudioChunk stream.
* Enforces a maximum retention window (privacy cap).
* Prebuffer: the last ``prebuffer_samples`` are kept before each
  new segment so the very start of a word is never clipped.
* Segment drain: ``drain_segment(n_samples)`` atomically removes
  and returns exactly n samples — used by the VAD to extract a
  completed speech segment.
* Thread-safe: a single ``threading.Lock`` guards all mutations.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)


class AudioBuffer:
    """
    Rolling ring-buffer for float32 PCM samples.

    Parameters
    ----------
    sample_rate:       samples per second (for duration calculations)
    max_buffer_sec:    hard cap on total buffered audio (privacy + memory)
    prebuffer_sec:     audio kept before speech onset to avoid clipping
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        max_buffer_sec: float = 30.0,
        prebuffer_sec: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate
        self._max_samples = int(max_buffer_sec * sample_rate)
        self._prebuffer_samples = int(prebuffer_sec * sample_rate)

        # deque gives O(1) append and O(n) slice — fine for our chunk sizes
        self._buf: deque[float] = deque(maxlen=self._max_samples)
        self._lock = threading.Lock()

        logger.debug(
            "AudioBuffer init sample_rate=%d max_sec=%.1f prebuf_sec=%.3f "
            "max_samples=%d prebuf_samples=%d",
            sample_rate,
            max_buffer_sec,
            prebuffer_sec,
            self._max_samples,
            self._prebuffer_samples,
        )

    # ── Write ────────────────────────────────────────────────────────────────

    def push(self, samples: np.ndarray) -> None:
        """Append a chunk of float32 samples; oldest samples evicted if at cap."""
        if samples.ndim != 1:
            samples = samples.flatten()
        with self._lock:
            self._buf.extend(samples.tolist())

    # ── Read ─────────────────────────────────────────────────────────────────

    def peek(self, n_samples: int | None = None) -> np.ndarray:
        """
        Return (a copy of) the last ``n_samples`` without consuming them.
        If ``n_samples`` is None, return the entire buffer.
        """
        with self._lock:
            if n_samples is None:
                data = list(self._buf)
            else:
                data = list(self._buf)[-n_samples:]
        return np.array(data, dtype=np.float32)

    def available(self) -> int:
        """Number of samples currently in the buffer."""
        with self._lock:
            return len(self._buf)

    def duration_sec(self) -> float:
        """Seconds of audio currently in the buffer."""
        return self.available() / self._sample_rate

    # ── Segment extraction ───────────────────────────────────────────────────

    def drain_segment(self, n_samples: int) -> np.ndarray:
        """
        Atomically remove and return exactly ``n_samples`` from the front
        of the buffer.  If fewer samples are available, returns what exists
        (caller is responsible for checking length).

        The prebuffer tail is *not* consumed — it is kept so the next
        segment starts with context.

        Returns
        -------
        np.ndarray  shape (n,) float32, n <= n_samples
        """
        with self._lock:
            available = len(self._buf)
            take = min(n_samples, available)
            segment: list[float] = []
            for _ in range(take):
                segment.append(self._buf.popleft())
        return np.array(segment, dtype=np.float32)

    def drain_all(self) -> np.ndarray:
        """Remove and return all buffered samples."""
        with self._lock:
            data = list(self._buf)
            self._buf.clear()
        return np.array(data, dtype=np.float32)

    def prebuffer_snapshot(self) -> np.ndarray:
        """
        Return a copy of the last ``prebuffer_samples`` currently in
        the buffer (do NOT consume).  Used to prepend to a new speech
        segment so the onset is captured.
        """
        with self._lock:
            data = list(self._buf)[-self._prebuffer_samples :]
        return np.array(data, dtype=np.float32)

    # ── Housekeeping ─────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Discard all buffered audio (privacy flush)."""
        with self._lock:
            self._buf.clear()
        logger.debug("AudioBuffer cleared")

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def max_samples(self) -> int:
        return self._max_samples

    @property
    def prebuffer_samples(self) -> int:
        return self._prebuffer_samples
