"""
bonbon_speech.stt.mock_stt
===========================
Deterministic mock STT backend for unit tests.

Features:
  * Returns canned responses from a list (wraps around).
  * Can be told to simulate ``block_sec`` latency.
  * Can be told to corrupt (raise) on specific call indices.
  * Can simulate low-confidence results.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np

from bonbon_speech.config.speech_config import STTConfig
from bonbon_speech.stt.base_stt import BaseSTT, TranscriptionResult


class MockSTT(BaseSTT):
    """
    Controllable mock STT.

    Parameters
    ----------
    responses:   Canned TranscriptionResult objects.  The mock cycles
                 through this list.  Defaults to one OK result.
    block_sec:   Artificial delay added to each _transcribe_impl call.
    corrupt_on:  Set of call-count indices at which to raise RuntimeError
                 (to test error-handling paths).
    """

    def __init__(
        self,
        cfg: STTConfig | None = None,
        responses: list[TranscriptionResult] | None = None,
        block_sec: float = 0.0,
        corrupt_on: Sequence[int] | None = None,
    ) -> None:
        if cfg is None:
            cfg = STTConfig()
        super().__init__(cfg)
        self._responses = responses or [
            TranscriptionResult(text="hello world", language="en", confidence=0.95)
        ]
        self._block_sec = block_sec
        self._corrupt_on = set(corrupt_on or [])
        self._call_idx = 0
        self.loaded = False
        # Introspection
        self.call_count = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        self.loaded = True
        self.reset_degraded()

    def unload(self) -> None:
        self.loaded = False

    # ── Inference ────────────────────────────────────────────────────────────

    def _transcribe_impl(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> TranscriptionResult:
        idx = self._call_idx
        self._call_idx += 1
        self.call_count += 1

        if self._block_sec > 0.0:
            time.sleep(self._block_sec)

        if idx in self._corrupt_on:
            raise RuntimeError(f"MockSTT intentional error on call {idx}")

        response = self._responses[idx % len(self._responses)]
        # Return a copy so caller can mutate freely
        return TranscriptionResult(
            text=response.text,
            language=response.language,
            confidence=response.confidence,
            is_low_confidence=response.is_low_confidence,
            is_timeout=response.is_timeout,
            is_silence=response.is_silence,
            words=list(response.words),
            word_start_times_sec=list(response.word_start_times_sec),
            word_end_times_sec=list(response.word_end_times_sec),
            word_confidences=list(response.word_confidences),
        )

    # ── Test helpers ─────────────────────────────────────────────────────────

    def set_responses(self, responses: list[TranscriptionResult]) -> None:
        self._responses = responses
        self._call_idx = 0

    def set_block(self, block_sec: float) -> None:
        self._block_sec = block_sec

    def reset_calls(self) -> None:
        self._call_idx = 0
        self.call_count = 0
