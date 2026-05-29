"""Abstract base class for face emotion analysis backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class FaceBackendInterface(ABC):
    """Interface that all face emotion backends must implement.

    Backends are responsible for:
    - Accepting a face-crop image (BGR or RGB numpy array).
    - Returning a standardised dictionary of emotion scores.
    - Providing a warmup method to load model weights before first use.
    - Reporting their readiness state via the ``is_ready`` property.
    """

    @abstractmethod
    def analyze(self, face_img: np.ndarray) -> dict:
        """Analyze a face crop image and return emotion scores.

        Args:
            face_img: A numpy array of shape (H, W, 3) representing the face
                crop.  May be BGR (OpenCV convention) or RGB depending on the
                backend.

        Returns:
            dict: Containing the following keys:
                - ``anger`` (float): Score in [0.0, 1.0].
                - ``disgust`` (float): Score in [0.0, 1.0].
                - ``fear`` (float): Score in [0.0, 1.0].
                - ``happiness`` (float): Score in [0.0, 1.0].
                - ``sadness`` (float): Score in [0.0, 1.0].
                - ``surprise`` (float): Score in [0.0, 1.0].
                - ``neutral`` (float): Score in [0.0, 1.0].
                - ``dominant_emotion`` (str): Name of the highest-scoring
                  emotion.
                - ``dominant_confidence`` (float): Score of the dominant
                  emotion in [0.0, 1.0].

        Raises:
            RuntimeError: If the backend is not ready or analysis fails.
        """

    @abstractmethod
    def warmup(self) -> None:
        """Pre-load model weights so the first real inference is fast.

        Implementations should catch all exceptions internally and set
        ``is_ready`` to ``False`` on failure rather than propagating the
        exception — this allows graceful degradation at runtime.
        """

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """Return True if the backend has loaded successfully and is usable."""
