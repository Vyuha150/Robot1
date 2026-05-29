"""Deterministic mock backends for testing and CI without ML dependencies."""

from __future__ import annotations

import itertools
from typing import Iterator

import numpy as np

from .face_backend_interface import FaceBackendInterface
from .voice_backend_interface import VoiceBackendInterface


# Cycle of emotions returned by MockFaceBackend, one per call.
_FACE_EMOTION_CYCLE: list[str] = [
    "neutral",
    "happiness",
    "sadness",
    "anger",
    "surprise",
]

_FACE_SCORES: dict[str, dict] = {
    "neutral": {
        "anger": 0.02, "disgust": 0.01, "fear": 0.01,
        "happiness": 0.05, "sadness": 0.03, "surprise": 0.02, "neutral": 0.86,
    },
    "happiness": {
        "anger": 0.02, "disgust": 0.01, "fear": 0.01,
        "happiness": 0.88, "sadness": 0.02, "surprise": 0.04, "neutral": 0.02,
    },
    "sadness": {
        "anger": 0.03, "disgust": 0.02, "fear": 0.05,
        "happiness": 0.02, "sadness": 0.82, "surprise": 0.02, "neutral": 0.04,
    },
    "anger": {
        "anger": 0.85, "disgust": 0.05, "fear": 0.02,
        "happiness": 0.01, "sadness": 0.03, "surprise": 0.02, "neutral": 0.02,
    },
    "surprise": {
        "anger": 0.02, "disgust": 0.01, "fear": 0.05,
        "happiness": 0.10, "sadness": 0.02, "surprise": 0.76, "neutral": 0.04,
    },
}


class MockFaceBackend(FaceBackendInterface):
    """Deterministic mock face backend for testing.

    Cycles through a fixed set of emotions on successive ``analyze`` calls so
    that test assertions can rely on predictable outputs without needing a GPU
    or a real camera feed.
    """

    def __init__(self) -> None:
        """Create the mock backend with an internal emotion cycling iterator."""
        self._ready: bool = False
        self._emotion_iter: Iterator[str] = itertools.cycle(_FACE_EMOTION_CYCLE)

    def warmup(self) -> None:
        """Mark the backend as ready — no actual loading is needed."""
        self._ready = True

    def analyze(self, face_img: np.ndarray) -> dict:
        """Return the next deterministic emotion from the cycle.

        Args:
            face_img: Ignored; present only to satisfy the interface contract.

        Returns:
            dict: Standardised emotion scores for the next emotion in the cycle.

        Raises:
            RuntimeError: If ``warmup`` has not been called.
        """
        if not self._ready:
            raise RuntimeError("MockFaceBackend not warmed up — call warmup() first.")

        emotion: str = next(self._emotion_iter)
        scores: dict = _FACE_SCORES[emotion].copy()
        return {
            **scores,
            "dominant_emotion": emotion,
            "dominant_confidence": scores[emotion],
        }

    @property
    def is_ready(self) -> bool:
        """Return True after warmup has been called."""
        return self._ready


class MockVoiceBackend(VoiceBackendInterface):
    """Deterministic mock voice backend for testing.

    Always returns ``neutral`` with high confidence so that voice-related test
    assertions have a stable baseline.
    """

    def __init__(self) -> None:
        """Create the mock backend in the not-ready state."""
        self._ready: bool = False

    def warmup(self) -> None:
        """Mark the backend as ready — no actual loading is needed."""
        self._ready = True

    def analyze_segment(self, audio_array: np.ndarray, sample_rate: int) -> dict:
        """Return a neutral, high-confidence voice emotion result.

        Args:
            audio_array: Ignored; present only to satisfy the interface.
            sample_rate: Ignored; present only to satisfy the interface.

        Returns:
            dict: Fixed neutral voice emotion scores.

        Raises:
            RuntimeError: If ``warmup`` has not been called.
        """
        if not self._ready:
            raise RuntimeError("MockVoiceBackend not warmed up — call warmup() first.")

        silence: bool = bool(
            len(audio_array) > 0 and float(np.max(np.abs(audio_array))) < 1e-6
        )

        return {
            "dominant_emotion": "neutral",
            "dominant_confidence": 0.9,
            "arousal": 0.2,
            "valence": 0.6,
            "arousal_valid": True,
            "valence_valid": True,
            "neutral_score": 0.9,
            "happy_score": 0.02,
            "sad_score": 0.02,
            "angry_score": 0.01,
            "fearful_score": 0.01,
            "stressed_score": 0.01,
            "calm_score": 0.02,
            "urgent_score": 0.01,
            "confused_score": 0.0,
            "noisy_audio": False,
            "silence_detected": silence,
            "model_failed": False,
            "backend_used": "mock",
        }

    @property
    def is_ready(self) -> bool:
        """Return True after warmup has been called."""
        return self._ready
