"""
bonbon_tts.backends.base_tts
==============================
Abstract base class for all TTS synthesis backends.

Every backend converts text → WAV bytes and reports its own availability.
Backends MUST be thread-safe when called from the synthesis worker thread.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Exception ──────────────────────────────────────────────────────────────────

class TTSError(Exception):
    """Raised when a synthesis backend fails to produce audio."""

    def __init__(self, message: str, error_code: str = "TTS_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class SynthesisOutput:
    """Result of a successful text-to-speech synthesis call."""

    # Raw WAV file bytes (44-byte header + PCM samples).
    wav_bytes: bytes

    # Estimated audio duration in seconds.
    duration_sec: float

    # The exact text that was synthesised.
    text: str

    # Sample rate of the WAV data (e.g. 22050 for Piper).
    sample_rate: int

    # Name of the backend that produced this output ("piper" | "mock").
    backend: str

    # True when this output was produced by the fallback backend
    # because the primary backend was unavailable.
    is_fallback: bool = False


# ── Abstract backend ─────────────────────────────────────────────────────────

class BaseTTS(ABC):
    """
    Abstract TTS synthesis backend.

    Subclass and implement `synthesize`, `is_available`, and `warmup`.

    Thread safety
    -------------
    `synthesize()` may be called from a background worker thread.
    Implementations must be safe for concurrent use (or protected
    internally with a lock if the underlying model is not re-entrant).
    """

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    @abstractmethod
    def warmup(self) -> None:
        """
        Load models and pre-allocate resources.

        Called once after the backend is created.  Should not raise
        (log warnings instead) so that degraded startup is possible.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if this backend can currently synthesise text.

        A backend may be temporarily unavailable (Piper process crashed)
        or permanently unavailable (not installed).
        """

    # ── Core operation ─────────────────────────────────────────────────────────

    @abstractmethod
    def synthesize(self, text: str) -> SynthesisOutput:
        """
        Convert *text* to audio.

        Parameters
        ----------
        text:
            Plain text to synthesise.  Do NOT pass SSML unless the
            backend explicitly supports it.

        Returns
        -------
        SynthesisOutput
            Contains WAV bytes, duration, sample rate, and backend name.

        Raises
        ------
        TTSError
            If synthesis fails for any reason.  The caller (SpeechSynthesizer)
            will catch this and invoke the fallback backend.
        """

    # ── Optional helpers ───────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Release resources.  Called when the node shuts down."""

    def backend_name(self) -> str:
        """Human-readable name for logging and health reports."""
        return type(self).__name__
