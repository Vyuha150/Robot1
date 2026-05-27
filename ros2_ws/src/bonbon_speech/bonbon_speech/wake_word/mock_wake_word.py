"""
bonbon_speech.wake_word.mock_wake_word
========================================
Controllable mock wake-word detector for unit tests.
"""

from __future__ import annotations

import numpy as np

from bonbon_speech.config.speech_config import WakeWordConfig
from bonbon_speech.wake_word.wake_word_detector import BaseWakeWordDetector


class MockWakeWordDetector(BaseWakeWordDetector):
    """
    Deterministic wake-word detector for testing.

    Parameters
    ----------
    detect_pattern:  Sequence of bool; True = detection.  Cycles.
    detect_score:    Score returned when detection=True.
    """

    def __init__(
        self,
        cfg: WakeWordConfig | None = None,
        detect_pattern: list[bool] | None = None,
        detect_score: float = 0.90,
    ) -> None:
        if cfg is None:
            cfg = WakeWordConfig()
        super().__init__(cfg)
        self._pattern = list(detect_pattern) if detect_pattern else [False]
        self._detect_score = detect_score
        self._idx = 0
        self._next_detect: bool | None = None  # one-shot override
        self.loaded = False
        self.call_count = 0
        self.detect_count = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def reset(self) -> None:
        self._idx = 0

    # ── Core ─────────────────────────────────────────────────────────────────

    def process_chunk(self, samples: np.ndarray) -> tuple[bool, float]:
        self.call_count += 1

        if self._next_detect is not None:
            detected = self._next_detect
            self._next_detect = None
        else:
            detected = self._pattern[self._idx % len(self._pattern)]
            self._idx += 1

        score = self._detect_score if detected else 0.0
        if detected:
            self.detect_count += 1
        return detected, score

    # ── Test helpers ─────────────────────────────────────────────────────────

    def set_pattern(self, pattern: list[bool]) -> None:
        self._pattern = list(pattern)
        self._idx = 0

    def force_detect(self) -> None:
        """Next process_chunk call will return True."""
        self._next_detect = True

    def force_no_detect(self) -> None:
        """Next process_chunk call will return False."""
        self._next_detect = False
