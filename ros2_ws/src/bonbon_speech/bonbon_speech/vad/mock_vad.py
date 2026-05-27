"""
bonbon_speech.vad.mock_vad
===========================
Controllable mock VAD for unit tests.

Usage::

    vad = MockVAD(sample_rate=16000)
    vad.load()

    # Configure speech detection sequence
    vad.set_speech_pattern([False]*3 + [True]*10 + [False]*5)

    # Or force next emit:
    vad.force_next_emit(samples=np.zeros(512, dtype=np.float32))

    seg = vad.process_chunk(chunk)   # returns AudioSegment or None
"""

from __future__ import annotations

import time

import numpy as np

from bonbon_speech.vad.base_vad import AudioSegment, BaseVAD


class MockVAD(BaseVAD):
    """
    Deterministic VAD for testing.

    Parameters
    ----------
    speech_pattern:   sequence of bool; True = speech chunk
                      Loops if exhausted (defaults to all-silence).
    emit_after:       emit a segment after this many speech chunks.
                      None = emit only on explicit force_next_emit().
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        speech_pattern: list[bool] | None = None,
        emit_after: int | None = None,
    ) -> None:
        super().__init__(sample_rate)
        self._pattern = list(speech_pattern) if speech_pattern else []
        self._emit_after = emit_after
        self._idx = 0
        self._speech_chunks = 0
        self._forced_emit: AudioSegment | None = None
        self._accumulated: list[float] = []
        self._onset_time: float = 0.0
        self.loaded = False
        # Introspection counters
        self.call_count = 0
        self.emit_count = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False
        self.reset()

    def reset(self) -> None:
        self._idx = 0
        self._speech_chunks = 0
        self._accumulated.clear()
        self._onset_time = 0.0
        self._forced_emit = None

    # ── Control API (for tests) ───────────────────────────────────────────────

    def set_speech_pattern(self, pattern: list[bool]) -> None:
        """Set the sequence of speech/silence booleans."""
        self._pattern = list(pattern)
        self._idx = 0

    def force_next_emit(
        self,
        samples: np.ndarray | None = None,
        force_cut: bool = False,
    ) -> None:
        """Force the next process_chunk call to emit a segment."""
        arr = samples if samples is not None else np.zeros(512, dtype=np.float32)
        self._forced_emit = AudioSegment(
            samples=arr,
            sample_rate=self._sample_rate,
            duration_sec=arr.size / self._sample_rate,
            onset_time=time.monotonic(),
            force_cut=force_cut,
        )

    # ── Core processing ───────────────────────────────────────────────────────

    def process_chunk(
        self,
        samples: np.ndarray,
        doa_angle_deg: float = 0.0,
    ) -> AudioSegment | None:
        self.call_count += 1

        # Honour explicit forced emit first
        if self._forced_emit is not None:
            seg = self._forced_emit
            self._forced_emit = None
            seg.doa_angle_deg = doa_angle_deg
            self.emit_count += 1
            self._accumulated.clear()
            return seg

        # Determine is_speech from pattern
        if self._pattern:
            is_speech = self._pattern[self._idx % len(self._pattern)]
            self._idx += 1
        else:
            is_speech = False

        if is_speech:
            if self._speech_chunks == 0:
                self._onset_time = time.monotonic()
            self._speech_chunks += 1
            self._accumulated.extend(samples.tolist())
        else:
            if self._speech_chunks > 0:
                # Transition: speech → silence → emit
                arr = np.array(self._accumulated, dtype=np.float32)
                seg = AudioSegment(
                    samples=arr,
                    sample_rate=self._sample_rate,
                    duration_sec=arr.size / self._sample_rate,
                    onset_time=self._onset_time,
                    force_cut=False,
                    doa_angle_deg=doa_angle_deg,
                )
                self._speech_chunks = 0
                self._accumulated.clear()
                self.emit_count += 1
                return seg

        # emit_after: emit every N speech chunks
        if self._emit_after and self._speech_chunks >= self._emit_after:
            arr = np.array(self._accumulated, dtype=np.float32)
            seg = AudioSegment(
                samples=arr,
                sample_rate=self._sample_rate,
                duration_sec=arr.size / self._sample_rate,
                onset_time=self._onset_time,
                force_cut=False,
                doa_angle_deg=doa_angle_deg,
            )
            self._speech_chunks = 0
            self._accumulated.clear()
            self.emit_count += 1
            return seg

        return None
