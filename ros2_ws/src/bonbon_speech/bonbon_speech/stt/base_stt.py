"""
bonbon_speech.stt.base_stt
===========================
Abstract base class for speech-to-text backends + TranscriptionResult.

Timeout / degraded-mode pattern (same as bonbon_vision BaseDetector):
  ThreadPoolExecutor.submit().result(timeout=N) — if the model hangs or
  exceeds inference_timeout_sec the future times out, ``consecutive_timeouts``
  increments, and the node may degrade to mock mode once the cap is reached.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
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
            self._consecutive_timeouts += 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.warning(
                "STT timeout #%d (limit=%ds elapsed=%.0fms)",
                self._consecutive_timeouts,
                self._cfg.inference_timeout_sec,
                elapsed_ms,
            )
            if self._consecutive_timeouts >= self._cfg.max_consecutive_timeouts:
                self._degraded = True
                logger.error(
                    "STT degraded: %d consecutive timeouts",
                    self._consecutive_timeouts,
                )
            return TranscriptionResult(
                is_timeout=True,
                inference_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.error("STT exception: %s (%.0f ms)", exc, elapsed_ms)
            return TranscriptionResult(
                is_timeout=False,
                inference_ms=elapsed_ms,
            )

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
