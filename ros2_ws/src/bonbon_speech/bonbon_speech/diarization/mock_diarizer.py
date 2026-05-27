"""
bonbon_speech.diarization.mock_diarizer
========================================
Controllable mock diarizer for unit tests.
"""

from __future__ import annotations

import time

import numpy as np

from bonbon_speech.config.speech_config import DiarizationConfig
from bonbon_speech.diarization.base_diarizer import (
    BaseDiarizer,
    DiarizationResult,
    SpeakerSegment,
)


class MockDiarizer(BaseDiarizer):
    """
    Deterministic diarizer for testing.

    Parameters
    ----------
    responses:  Sequence of DiarizationResult to return (cycles).
    block_sec:  Artificial delay to simulate slow inference.
    """

    def __init__(
        self,
        cfg: DiarizationConfig | None = None,
        responses: list[DiarizationResult] | None = None,
        block_sec: float = 0.0,
    ) -> None:
        if cfg is None:
            cfg = DiarizationConfig()
        super().__init__(cfg)
        self._responses = responses or [
            DiarizationResult(
                segments=[SpeakerSegment("SPEAKER_00", 0.0, 1.0, 1.0)],
                dominant_speaker="SPEAKER_00",
                all_speaker_ids=["SPEAKER_00"],
            )
        ]
        self._block_sec = block_sec
        self._call_idx = 0
        self.loaded = False
        self.call_count = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    # ── Diarization ─────────────────────────────────────────────────────────

    def diarize(
        self,
        samples: np.ndarray,
        sample_rate: int = 16000,
    ) -> DiarizationResult:
        self.call_count += 1

        if self._block_sec > 0.0:
            time.sleep(self._block_sec)

        result = self._responses[self._call_idx % len(self._responses)]
        self._call_idx += 1
        return result

    # ── Test helpers ─────────────────────────────────────────────────────────

    def set_responses(self, responses: list[DiarizationResult]) -> None:
        self._responses = responses
        self._call_idx = 0

    def set_block(self, block_sec: float) -> None:
        self._block_sec = block_sec
