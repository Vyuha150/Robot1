"""Abstract base class for voice/tone-of-voice emotion analysis backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class VoiceBackendInterface(ABC):
    """Interface that all voice emotion backends must implement.

    Backends accept raw PCM audio arrays and return standardised emotion
    dictionaries covering arousal/valence dimensions as well as discrete
    emotion categories.
    """

    @abstractmethod
    def analyze_segment(self, audio_array: np.ndarray, sample_rate: int) -> dict:
        """Analyze a PCM audio segment and return emotion scores.

        Args:
            audio_array: 1-D float32 numpy array of PCM samples normalised to
                [-1.0, 1.0].
            sample_rate: Sample rate of ``audio_array`` in Hz (e.g. 16000).

        Returns:
            dict: Containing the following keys:
                - ``dominant_emotion`` (str): One of neutral, happy, sad,
                  angry, fearful, stressed, calm, urgent, confused.
                - ``dominant_confidence`` (float): Confidence in [0.0, 1.0].
                - ``arousal`` (float): Arousal dimension [0.0, 1.0].
                - ``valence`` (float): Valence dimension [0.0, 1.0].
                - ``arousal_valid`` (bool): Whether arousal value is reliable.
                - ``valence_valid`` (bool): Whether valence value is reliable.
                - Individual score keys: ``neutral_score``, ``happy_score``,
                  ``sad_score``, ``angry_score``, ``fearful_score``,
                  ``stressed_score``, ``calm_score``, ``urgent_score``,
                  ``confused_score``.
                - ``noisy_audio`` (bool): True if high background noise was
                  detected.
                - ``silence_detected`` (bool): True if the segment is mostly
                  silence.
                - ``model_failed`` (bool): True if inference raised an error.
                - ``backend_used`` (str): Name of the backend.

        Raises:
            RuntimeError: If the backend is not ready.
        """

    @abstractmethod
    def warmup(self) -> None:
        """Pre-load model weights so the first real inference is fast.

        Implementations should catch all exceptions internally and set
        ``is_ready`` to ``False`` on failure rather than propagating the
        exception.
        """

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the backend has loaded successfully and is usable."""
