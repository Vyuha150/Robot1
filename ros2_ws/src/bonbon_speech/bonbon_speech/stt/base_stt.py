"""
bonbon_speech.stt.base_stt
===========================
Abstract base class for speech-to-text backends + TranscriptionResult.

Timeout / degraded-mode pattern (same as bonbon_vision BaseDetector):
  ThreadPoolExecutor.submit().result(timeout=N) — if the model hangs or
  exceeds inference_timeout_sec the future times out, ``consecutive_timeouts``
  increments, and the node may degrade to mock mode once the cap is reached.

Important caveat — timeouts are NOT cancellation:
  ThreadPoolExecutor cannot preempt a task that has already started, so a
  timed-out call keeps running on the single worker thread. With
  ``max_workers=1`` (deliberate: one concurrent inference bounds CPU/memory
  on embedded hardware), a naive implementation would let the *next*
  transcribe() call queue behind that abandoned task and silently burn its
  own timeout budget waiting for a worker that was never going to be free in
  time — turning one slow call into a cascade of spurious timeouts. Instead,
  ``transcribe()`` tracks the abandoned future and fails fast (no queuing)
  while it is still draining; once it actually finishes, normal operation
  resumes automatically. This keeps the "one worker = one concurrent
  inference" resource bound intact while avoiding the cascade.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

import numpy as np

from bonbon_speech.config.speech_config import STTConfig

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """
    Output of one STT inference pass.

    text:            Recognised transcript (empty on silence/timeout).
    language:        Detected or forced language code ("en", "zh", …).
    confidence:      Mean log-prob converted to [0, 1] by Whisper, or
                     heuristic for other backends.
    is_low_confidence: True when confidence < STTConfig.confidence_threshold.
    is_timeout:      True when the inference wall-clock limit was hit.
    is_silence:      True when the segment was effectively empty / silent.
    words:           Per-word transcriptions (requires word_timestamps=True).
    word_start_times_sec: aligned with ``words``.
    word_end_times_sec:   aligned with ``words``.
    word_confidences:     per-word confidence [0, 1] aligned with ``words``.
    inference_ms:    Wall-clock inference time in milliseconds.
    """

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    is_low_confidence: bool = False
    is_timeout: bool = False
    is_silence: bool = False
    words: list[str] = field(default_factory=list)
    word_start_times_sec: list[float] = field(default_factory=list)
    word_end_times_sec: list[float] = field(default_factory=list)
    word_confidences: list[float] = field(default_factory=list)
    inference_ms: float = 0.0


class BaseSTT(ABC):
    """
    Abstract STT interface with built-in timeout + consecutive-failure tracking.

    Subclasses implement:
        load()     — load model weights
        unload()   — release resources
        _transcribe_impl(samples, sample_rate) -> TranscriptionResult

    Public consumers call:
        transcribe(samples, sample_rate) -> TranscriptionResult
    which wraps ``_transcribe_impl`` with a thread-pool timeout guard.
    """

    def __init__(self, cfg: STTConfig) -> None:
        self._cfg = cfg
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        self._consecutive_timeouts = 0
        self._degraded = False
        # Future left running on the single worker after a previous call
        # timed out. Tracked so the next transcribe() can fail fast instead
        # of queuing behind it (see module docstring).
        self._pending_future: Future | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @abstractmethod
    def load(self) -> None:
        """Load model.  Must be idempotent."""
        ...

    @abstractmethod
    def unload(self) -> None:
        """Release model resources."""
        ...

    # ── Core (implemented by subclasses) ─────────────────────────────────────

    @abstractmethod
    def _transcribe_impl(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> TranscriptionResult:
        """
        Run one inference pass synchronously.
        Called from a worker thread inside transcribe().
        """
        ...

    # ── Public API ───────────────────────────────────────────────────────────

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int = 16000,
    ) -> TranscriptionResult:
        """
        Transcribe *samples* with timeout + degraded-mode guard.

        Returns a TranscriptionResult; never raises.
        """
        if samples.size == 0:
            return TranscriptionResult(is_silence=True)

        t0 = time.monotonic()

        if self._pending_future is not None:
            if self._pending_future.done():
                self._pending_future = None
            else:
                # The single worker is still draining a previously abandoned
                # call. Fail fast rather than queuing behind it and waiting
                # out our own timeout for a worker we already know is busy.
                logger.warning(
                    "STT busy: previous inference still running on the single "
                    "worker, rejecting immediately (#%d)",
                    self._consecutive_timeouts + 1,
                )
                return self._record_timeout(time.monotonic() - t0)

        future = self._executor.submit(self._transcribe_impl, samples, sample_rate)
        try:
            result = future.result(timeout=self._cfg.inference_timeout_sec)
            self._consecutive_timeouts = 0
            result.inference_ms = (time.monotonic() - t0) * 1000.0
            # Apply confidence gate
            if result.confidence < self._cfg.confidence_threshold:
                result.is_low_confidence = True
            logger.debug(
                "STT ok text=%r lang=%r conf=%.3f ms=%.1f",
                result.text[:60],
                result.language,
                result.confidence,
                result.inference_ms,
            )
            return result
        except FutureTimeout:
            elapsed_sec = time.monotonic() - t0
            logger.warning(
                "STT timeout #%d (limit=%ds elapsed=%.0fms)",
                self._consecutive_timeouts + 1,
                self._cfg.inference_timeout_sec,
                elapsed_sec * 1000.0,
            )
            # Can't cancel a task that's already started — remember the
            # future so the next call doesn't queue behind it.
            self._pending_future = future
            future.add_done_callback(self._log_abandoned_outcome)
            return self._record_timeout(elapsed_sec)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.error("STT exception: %s (%.0f ms)", exc, elapsed_ms)
            return TranscriptionResult(
                is_timeout=False,
                inference_ms=elapsed_ms,
            )

    def _record_timeout(self, elapsed_sec: float) -> TranscriptionResult:
        """Bump the consecutive-timeout counter, degrade if past the cap."""
        self._consecutive_timeouts += 1
        if self._consecutive_timeouts >= self._cfg.max_consecutive_timeouts:
            self._degraded = True
            logger.error(
                "STT degraded: %d consecutive timeouts",
                self._consecutive_timeouts,
            )
        return TranscriptionResult(
            is_timeout=True,
            inference_ms=elapsed_sec * 1000.0,
        )

    @staticmethod
    def _log_abandoned_outcome(future: Future) -> None:
        """Best-effort observability for a call that timed out: log how it
        actually turned out once it eventually finishes (result is discarded
        either way — the caller already moved on)."""
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            logger.warning("STT abandoned inference eventually failed: %s", exc)
        else:
            logger.info("STT abandoned inference eventually completed (result discarded)")

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    @property
    def consecutive_timeouts(self) -> int:
        return self._consecutive_timeouts

    def reset_degraded(self) -> None:
        """Reset degraded state (e.g., after model reload)."""
        self._degraded = False
        self._consecutive_timeouts = 0
