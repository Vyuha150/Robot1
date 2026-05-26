"""
bonbon_tts.backends.mock_tts
==============================
Mock TTS backend for tests and CI.

Produces a short beep WAV instead of real speech.
No network access, no model files, no external dependencies.

Also exposes `generate_beep_wav()` as a standalone utility function used
by FillerPlayer.generate_builtin() to create minimal filler WAV files.
"""
from __future__ import annotations

import io
import logging
import math
import struct
import threading
import time
import wave
from typing import List, Optional

from bonbon_tts.backends.base_tts import BaseTTS, SynthesisOutput, TTSError

logger = logging.getLogger(__name__)


# ── WAV generation utility ────────────────────────────────────────────────────

def generate_beep_wav(
    duration_sec: float = 0.15,
    freq_hz: float = 440.0,
    sample_rate: int = 22050,
    amplitude: float = 0.20,
) -> bytes:
    """
    Generate a minimal mono 16-bit PCM WAV with a sine-wave tone.

    Pure Python — uses only the stdlib `wave`, `math`, and `struct` modules.

    Parameters
    ----------
    duration_sec:
        Length of the beep.
    freq_hz:
        Tone frequency.
    sample_rate:
        Audio sample rate.
    amplitude:
        Peak amplitude (0.0–1.0).  Keep below 0.5 to avoid clipping.

    Returns
    -------
    bytes
        Complete WAV file bytes including the 44-byte header.
    """
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)     # 16-bit
        wf.setframerate(sample_rate)
        for i in range(num_samples):
            val = int(32767 * amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            wf.writeframes(struct.pack("<h", val))
    return buf.getvalue()


def generate_silence_wav(
    duration_sec: float = 0.3,
    sample_rate: int = 22050,
) -> bytes:
    """Generate a WAV file containing silence (all zeros)."""
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)
    return buf.getvalue()


# ── Mock backend ──────────────────────────────────────────────────────────────

class MockTTS(BaseTTS):
    """
    Test-double TTS backend.

    Produces a short beep whose duration scales with text length
    (50 ms per character, capped at 2 s), making test timing predictable.

    Attributes available for test inspection
    ----------------------------------------
    synthesized_texts : list[str]
        All texts passed to synthesize() in call order.
    call_count : int
        Total number of synthesize() calls.
    fail_next : bool
        Set to True to make the next synthesize() raise TTSError.
    """

    SAMPLE_RATE = 22050
    MS_PER_CHAR = 10      # simulated speaking rate for test timing
    MAX_DURATION_SEC = 2.0

    def __init__(
        self,
        simulate_latency_ms: float = 0.0,
        fail_next: bool = False,
    ) -> None:
        self._sim_latency_ms = simulate_latency_ms
        self._fail_next      = fail_next
        self._lock           = threading.Lock()

        # Inspection state
        self.synthesized_texts: List[str] = []
        self.call_count:        int       = 0

    # ── BaseTTS interface ──────────────────────────────────────────────────────

    def warmup(self) -> None:
        logger.debug("MockTTS: warmup (no-op)")

    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str) -> SynthesisOutput:
        with self._lock:
            self.call_count += 1
            self.synthesized_texts.append(text)

            if self._fail_next:
                self._fail_next = False
                raise TTSError("Simulated TTS failure", "MOCK_FAIL")

        if self._sim_latency_ms > 0:
            time.sleep(self._sim_latency_ms / 1000.0)

        duration_sec = min(
            len(text) * self.MS_PER_CHAR / 1000.0,
            self.MAX_DURATION_SEC,
        )
        wav_bytes = generate_beep_wav(
            duration_sec=max(0.05, duration_sec),
            freq_hz=440.0,
            sample_rate=self.SAMPLE_RATE,
        )
        return SynthesisOutput(
            wav_bytes    = wav_bytes,
            duration_sec = duration_sec,
            text         = text,
            sample_rate  = self.SAMPLE_RATE,
            backend      = "mock",
        )

    def backend_name(self) -> str:
        return "mock"

    # ── Test helpers ───────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear inspection state for a fresh test."""
        with self._lock:
            self.synthesized_texts.clear()
            self.call_count = 0
            self._fail_next = False

    @property
    def fail_next(self) -> bool:
        return self._fail_next

    @fail_next.setter
    def fail_next(self, value: bool) -> None:
        self._fail_next = value
