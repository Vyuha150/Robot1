"""
bonbon_speech.diarization.base_diarizer
========================================
Abstract base class for speaker diarization backends + SpeakerSegment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from bonbon_speech.config.speech_config import DiarizationConfig


@dataclass
class SpeakerSegment:
    """
    One speaker turn identified by the diarization backend.

    speaker_id:   normalised ID, e.g. "SPEAKER_00", "SPEAKER_01"
    start_sec:    start offset within the submitted audio (seconds)
    end_sec:      end offset
    confidence:   backend-specific score in [0, 1]
    """

    speaker_id: str = "SPEAKER_00"
    start_sec: float = 0.0
    end_sec: float = 0.0
    confidence: float = 1.0

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


@dataclass
class DiarizationResult:
    """
    Complete diarization output for one audio segment.

    segments:         list of SpeakerSegment (may be empty)
    dominant_speaker: speaker_id with the longest total speaking time
    all_speaker_ids:  de-duplicated list of speaker IDs present
    is_timeout:       True when the backend hit its inference deadline
    """

    segments: list[SpeakerSegment] = field(default_factory=list)
    dominant_speaker: str = "SPEAKER_00"
    all_speaker_ids: list[str] = field(default_factory=list)
    is_timeout: bool = False

    def __post_init__(self):
        if not self.all_speaker_ids and self.segments:
            seen = []
            for s in self.segments:
                if s.speaker_id not in seen:
                    seen.append(s.speaker_id)
            self.all_speaker_ids = seen
        if not self.dominant_speaker and self.segments:
            # Pick speaker with most cumulative speech
            acc: dict = {}
            for s in self.segments:
                acc[s.speaker_id] = acc.get(s.speaker_id, 0.0) + s.duration_sec
            self.dominant_speaker = max(acc, key=acc.__getitem__)


class BaseDiarizer(ABC):
    """
    Abstract diarization interface.

    Lifecycle:
        1. ``load()``
        2. ``diarize(samples, sample_rate)`` → DiarizationResult
        3. ``unload()``
    """

    def __init__(self, cfg: DiarizationConfig) -> None:
        self._cfg = cfg

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...

    @abstractmethod
    def diarize(
        self,
        samples: np.ndarray,
        sample_rate: int = 16000,
    ) -> DiarizationResult:
        """
        Run diarization on a complete speech segment.

        Returns
        -------
        DiarizationResult with zero or more SpeakerSegments.
        Must never raise — return is_timeout=True on failure.
        """
        ...
