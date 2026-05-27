"""
bonbon_tts.speaker.speaker_bridge
====================================
Speaker abstraction layer decoupling the TTS core from the HAL driver.

Architecture
------------
::

    SpeechSynthesizer
          │
          ▼
    AbstractSpeakerBridge  ─── interface
          ├── SpeakerBridge       (production: wraps bonbon_hal.SpeakerDriver)
          └── MockSpeakerBridge   (tests: records calls, no audio device)

``SpeakerBridge`` tries to import ``bonbon_hal`` at init time; if the
package is absent it raises ``ImportError`` immediately so the node can
fall back to ``MockSpeakerBridge``.

``MockSpeakerBridge`` is completely self-contained with no extra deps,
making TTS unit tests possible on any machine.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ── Abstract interface ────────────────────────────────────────────────────────


class AbstractSpeakerBridge(ABC):
    """
    Minimal audio-playback interface used by ``SpeechSynthesizer``.

    Implementations must be thread-safe — ``play`` may be called from the
    synthesis worker thread while ``stop`` is called from the main thread.
    """

    @abstractmethod
    def play(self, wav_bytes: bytes) -> None:
        """
        Play *wav_bytes* (complete WAV file) synchronously.

        Should block until playback finishes.  Raises on unrecoverable
        hardware errors; transient errors should be logged and swallowed.
        """

    @abstractmethod
    def stop(self) -> None:
        """Interrupt any in-progress playback immediately."""

    @abstractmethod
    def is_playing(self) -> bool:
        """Return True if audio is currently being played."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the underlying audio device is accessible."""

    def set_volume(self, pct: float) -> None:
        """Set playback volume (0–100).  Optional; default is a no-op."""

    def backend_name(self) -> str:
        return type(self).__name__


# ── Production bridge (HAL) ───────────────────────────────────────────────────


class SpeakerBridge(AbstractSpeakerBridge):
    """
    Production speaker bridge backed by ``bonbon_hal.SpeakerDriver``.

    Parameters
    ----------
    device:
        Audio device name passed to the HAL driver (e.g. ``"default"``).
    volume_pct:
        Initial volume (0–100).
    sample_rate:
        Sample rate of WAV audio the driver will receive.
    channels:
        Number of audio channels.

    Raises
    ------
    ImportError
        If ``bonbon_hal`` is not installed.
    """

    def __init__(
        self,
        device: str = "default",
        volume_pct: float = 80.0,
        sample_rate: int = 22050,
        channels: int = 1,
    ) -> None:
        # Hard import — fail fast if HAL not available
        from bonbon_hal.drivers.speaker_driver import SpeakerDriver  # type: ignore[import]

        self._driver = SpeakerDriver(
            device=device,
            sample_rate=sample_rate,
            channels=channels,
        )
        self._driver.initialize()
        self._volume_pct = volume_pct
        self._driver.set_volume(volume_pct)
        logger.info("SpeakerBridge ready: device=%r volume=%.0f%%", device, volume_pct)

    # ── AbstractSpeakerBridge ──────────────────────────────────────────────────

    def play(self, wav_bytes: bytes) -> None:
        self._driver.play_wav(wav_bytes)

    def stop(self) -> None:
        self._driver.stop()

    def is_playing(self) -> bool:
        return self._driver.is_playing()

    def is_available(self) -> bool:
        try:
            return self._driver.is_available()
        except Exception:
            return False

    def set_volume(self, pct: float) -> None:
        self._volume_pct = pct
        self._driver.set_volume(pct)

    def backend_name(self) -> str:
        return "hal_speaker"


# ── Mock bridge (tests) ───────────────────────────────────────────────────────


class MockSpeakerBridge(AbstractSpeakerBridge):
    """
    Test-double speaker bridge — records calls but plays no audio.

    Attributes available for inspection
    ------------------------------------
    play_calls : list[bytes]
        WAV bytes passed to each ``play()`` call in order.
    stop_count : int
        Number of ``stop()`` calls.
    playing_duration_sec : float
        Sum of simulated play durations (based on WAV header).
    fail_next_play : bool
        When True the next ``play()`` call raises ``RuntimeError``.

    Parameters
    ----------
    simulate_play_blocking:
        When True ``play()`` sleeps for the actual WAV duration, matching
        real playback timing.  Default False for fast tests.
    available:
        Initial value returned by ``is_available()``.
    """

    def __init__(
        self,
        simulate_play_blocking: bool = False,
        available: bool = True,
    ) -> None:
        self._simulate_blocking = simulate_play_blocking
        self._available = available
        self._lock = threading.Lock()

        # Inspection state
        self.play_calls: list[bytes] = []
        self.stop_count: int = 0
        self.playing_duration_sec: float = 0.0
        self.fail_next_play: bool = False

        # Internal "playing" flag
        self._playing = False

    # ── AbstractSpeakerBridge ──────────────────────────────────────────────────

    def play(self, wav_bytes: bytes) -> None:
        with self._lock:
            if self.fail_next_play:
                self.fail_next_play = False
                raise RuntimeError("Simulated speaker failure")
            self.play_calls.append(wav_bytes)
            self._playing = True

        duration = self._wav_duration(wav_bytes)

        if self._simulate_blocking and duration > 0:
            time.sleep(duration)

        with self._lock:
            self.playing_duration_sec += duration
            self._playing = False

    def stop(self) -> None:
        with self._lock:
            self.stop_count += 1
            self._playing = False

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def is_available(self) -> bool:
        return self._available

    def backend_name(self) -> str:
        return "mock_speaker"

    # ── Test helpers ───────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all recorded state for a fresh test."""
        with self._lock:
            self.play_calls.clear()
            self.stop_count = 0
            self.playing_duration_sec = 0.0
            self.fail_next_play = False
            self._playing = False

    @property
    def play_count(self) -> int:
        """Total number of play() calls."""
        with self._lock:
            return len(self.play_calls)

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _wav_duration(wav_bytes: bytes) -> float:
        """
        Extract duration from WAV header without importing ``wave``.

        Returns 0.0 on any parse error.
        """
        try:
            import io
            import wave

            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            return 0.0
