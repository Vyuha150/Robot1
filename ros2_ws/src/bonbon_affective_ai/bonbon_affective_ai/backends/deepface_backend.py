"""DeepFace-based face emotion analysis backend."""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .face_backend_interface import FaceBackendInterface

logger = logging.getLogger(__name__)


class DeepFaceBackend(FaceBackendInterface):
    """Face emotion backend using the DeepFace library.

    DeepFace is an optional dependency.  If it is not installed, ``warmup``
    marks the backend as not-ready and ``analyze`` raises ``RuntimeError``.
    This allows the rest of the system to continue operating with a mock
    backend or without face analysis.
    """

    def __init__(self) -> None:
        """Initialise the DeepFace backend in the not-ready state."""
        self._ready: bool = False
        self._model: Optional[Any] = None  # holds the DeepFace module

    def warmup(self) -> None:
        """Load DeepFace and run a single blank-image warmup pass.

        Sets ``_ready`` to True on success or False on any exception so that
        the rest of the system can degrade gracefully.
        """
        try:
            from deepface import DeepFace  # type: ignore[import]

            # Run with a trivial image to load model weights into memory.
            blank = np.zeros((48, 48, 3), dtype=np.uint8)
            DeepFace.analyze(
                blank,
                actions=["emotion"],
                enforce_detection=False,
                silent=True,
            )
            self._model = DeepFace
            self._ready = True
            logger.info("DeepFace backend warmed up successfully.")
        except ImportError:
            logger.warning(
                "DeepFace is not installed.  Face emotion analysis will be "
                "unavailable.  Install with: pip install deepface"
            )
            self._ready = False
        except Exception as exc:
            logger.warning("DeepFace warmup failed: %s", exc)
            self._ready = False

    def analyze(self, face_img: np.ndarray) -> dict:
        """Analyse a face crop and return normalised emotion scores.

        Args:
            face_img: BGR or RGB numpy array of shape (H, W, 3).

        Returns:
            dict: Standardised emotion scores (see ``FaceBackendInterface``).

        Raises:
            RuntimeError: If the backend is not ready or DeepFace fails.
        """
        if not self._ready or self._model is None:
            raise RuntimeError(
                "DeepFace backend is not ready.  Call warmup() first."
            )

        try:
            result = self._model.analyze(
                face_img,
                actions=["emotion"],
                enforce_detection=False,
                silent=True,
            )
            # DeepFace may return a list when multiple faces are detected.
            if isinstance(result, list):
                result = result[0]

            emotions: dict = result.get("emotion", {})
            dominant: str = result.get("dominant_emotion", "neutral")
            conf: float = emotions.get(dominant, 50.0) / 100.0

            return {
                "anger": float(emotions.get("angry", 0)) / 100.0,
                "disgust": float(emotions.get("disgust", 0)) / 100.0,
                "fear": float(emotions.get("fear", 0)) / 100.0,
                "happiness": float(emotions.get("happy", 0)) / 100.0,
                "sadness": float(emotions.get("sad", 0)) / 100.0,
                "surprise": float(emotions.get("surprise", 0)) / 100.0,
                "neutral": float(emotions.get("neutral", 0)) / 100.0,
                "dominant_emotion": dominant,
                "dominant_confidence": conf,
            }
        except Exception as exc:
            raise RuntimeError(f"DeepFace analysis failed: {exc}") from exc

    @property
    def is_ready(self) -> bool:
        """Return True if DeepFace is loaded and ready for inference."""
        return self._ready
