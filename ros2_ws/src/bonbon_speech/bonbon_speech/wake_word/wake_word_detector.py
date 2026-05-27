"""
bonbon_speech.wake_word.wake_word_detector
===========================================
Abstract wake-word detector interface + openWakeWord placeholder backend.

The wake-word gate sits *before* VAD: audio chunks are fed continuously,
and the detector signals when the configured keyword phrase is heard.
After a positive detection the pipeline arms VAD for
``listen_timeout_sec`` before re-arming the wake-word detector.

Backend enumeration
-------------------
``"mock"``         → MockWakeWordDetector (tests / development)
``"openwakeword"`` → OpenWakeWordDetector  (real inference)
``"porcupine"``    → (placeholder — not yet implemented)

Factory usage::

    from bonbon_speech.wake_word.wake_word_detector import make_wake_word_detector
    detector = make_wake_word_detector(cfg)
    detector.load()
    detected, score = detector.process_chunk(samples)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

from bonbon_speech.config.speech_config import WakeWordConfig

logger = logging.getLogger(__name__)


class BaseWakeWordDetector(ABC):
    """Abstract interface for wake-word detection backends."""

    def __init__(self, cfg: WakeWordConfig) -> None:
        self._cfg = cfg

    @abstractmethod
    def load(self) -> None:
        """Load model / resources.  Idempotent."""
        ...

    @abstractmethod
    def unload(self) -> None:
        """Release resources."""
        ...

    @abstractmethod
    def process_chunk(
        self,
        samples: np.ndarray,
    ) -> tuple[bool, float]:
        """
        Feed one audio chunk.

        Returns
        -------
        (detected, score)
            detected: True when the keyword was heard above threshold.
            score:    raw detector confidence in [0, 1].
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming state."""
        ...


class OpenWakeWordDetector(BaseWakeWordDetector):
    """
    openWakeWord-based keyword detector.

    https://github.com/dscripka/openWakeWord

    Requires ``pip install openwakeword``.
    The keyword model file (*.tflite / *.onnx) is set via
    WakeWordConfig.model_path — not hardcoded.
    """

    def __init__(self, cfg: WakeWordConfig) -> None:
        super().__init__(cfg)
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return  # idempotent

        try:
            from openwakeword.model import Model as OWWModel  # type: ignore

            if self._cfg.model_path:
                logger.info(
                    "OpenWakeWordDetector loading model path=%s",
                    self._cfg.model_path,
                )
                self._model = OWWModel(
                    wakeword_models=[self._cfg.model_path],
                    inference_framework="tflite",
                )
            else:
                # Built-in model closest to the configured keyword
                logger.info(
                    "OpenWakeWordDetector using built-in model for keyword=%r",
                    self._cfg.keyword,
                )
                self._model = OWWModel(
                    inference_framework="tflite",
                )
            logger.info("OpenWakeWordDetector loaded ok")
        except Exception as exc:
            logger.error("OpenWakeWordDetector load failed: %s", exc)
            raise

    def unload(self) -> None:
        self._model = None

    def reset(self) -> None:
        if self._model is not None:
            try:
                self._model.reset()
            except Exception:
                pass

    def process_chunk(self, samples: np.ndarray) -> tuple[bool, float]:
        if self._model is None:
            return False, 0.0

        try:
            # openWakeWord expects int16 or float32, shape (n_samples,)
            pcm = (samples * 32768).clip(-32768, 32767).astype("int16")
            pred = self._model.predict(pcm)
            # pred is {model_name: score} — pick the highest score
            score = float(max(pred.values())) if pred else 0.0
            detected = score >= self._cfg.threshold
            if detected:
                logger.info(
                    "Wake word detected keyword=%r score=%.3f",
                    self._cfg.keyword,
                    score,
                )
            return detected, score
        except Exception as exc:
            logger.warning("OpenWakeWordDetector predict error: %s", exc)
            return False, 0.0


# ── Factory ───────────────────────────────────────────────────────────────────


def make_wake_word_detector(cfg: WakeWordConfig) -> BaseWakeWordDetector:
    """Instantiate the configured wake-word backend."""
    if cfg.backend == "openwakeword":
        return OpenWakeWordDetector(cfg)
    elif cfg.backend == "mock":
        from bonbon_speech.wake_word.mock_wake_word import MockWakeWordDetector

        return MockWakeWordDetector(cfg)
    else:
        raise ValueError(f"Unknown wake_word backend: {cfg.backend!r}")
