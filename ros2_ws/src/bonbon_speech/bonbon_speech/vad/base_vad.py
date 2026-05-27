"""
bonbon_speech.vad.base_vad
===========================
Abstract base class for Voice Activity Detection backends + AudioSegment
dataclass returned when a complete speech segment is detected.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class AudioSegment:
    """
    A completed speech segment emitted by a VAD backend.

    Attributes
    ----------
    samples:        float32 PCM samples at the configured sample_rate
    sample_rate:    samples per second
    duration_sec:   pre-computed duration (samples / sample_rate)
    onset_time:     wall-clock time.monotonic() when first speech was detected
    force_cut:      True when the segment was emitted due to max_speech_sec
    doa_angle_deg:  direction-of-arrival if available from the HAL mic
    """

    samples: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    sample_rate: int = 16000
    duration_sec: float = 0.0
    onset_time: float = field(default_factory=time.monotonic)
    force_cut: bool = False
    doa_angle_deg: float = 0.0

    def __post_init__(self):
        if self.duration_sec == 0.0 and self.samples.size > 0:
            self.duration_sec = self.samples.size / self.sample_rate


class BaseVAD(ABC):
    """
    Abstract VAD interface.

    Implementations receive a stream of audio chunks (numpy arrays) and
    emit AudioSegment objects when speech has ended (or been force-cut).

    Lifecycle:
        1. Instantiate with VADConfig
        2. Call ``load()`` once to load the model
        3. Feed chunks via ``process_chunk(samples, doa_angle_deg)``
           — returns a completed AudioSegment or None
        4. Call ``reset()`` to discard partial state between sessions
        5. Call ``unload()`` to free model resources
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self._sample_rate = sample_rate

    @abstractmethod
    def load(self) -> None:
        """Load the VAD model.  Must be idempotent."""
        ...

    @abstractmethod
    def unload(self) -> None:
        """Release model resources."""
        ...

    @abstractmethod
    def process_chunk(
        self,
        samples: np.ndarray,
        doa_angle_deg: float = 0.0,
    ) -> AudioSegment | None:
        """
        Feed one audio chunk to the VAD state machine.

        Parameters
        ----------
        samples:       float32 array, length = chunk_size_samples
        doa_angle_deg: direction-of-arrival from HAL (pass-through to segment)

        Returns
        -------
        AudioSegment when speech ended (or force-cut); None otherwise.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Discard any partial speech state (call between sessions)."""
        ...

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
