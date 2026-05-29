"""SpeechBrain-based voice emotion analysis backend."""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .voice_backend_interface import VoiceBackendInterface

logger = logging.getLogger(__name__)

_EMOTION_LABELS: list[str] = [
    "neutral", "happy", "sad", "angry", "fearful",
    "stressed", "calm", "urgent", "confused",
]


class SpeechBrainBackend(VoiceBackendInterface):
    """Voice emotion backend using SpeechBrain's emotion recognition model.

    SpeechBrain is an optional dependency.  If it is not installed, ``warmup``
    marks the backend as not-ready and analysis returns a model-failed result
    rather than raising — enabling graceful degradation.
    """

    _MODEL_SOURCE: str = "speechbrain/emotion-recognition-wav2vec2-IEMOCAP"

    def __init__(self) -> None:
        """Initialise the SpeechBrain backend in the not-ready state."""
        self._ready: bool = False
        self._classifier: Optional[Any] = None

    def warmup(self) -> None:
        """Load the SpeechBrain emotion-recognition model.

        Downloads the model to ``~/.cache/huggingface`` on first run.
        Sets ``_ready`` to False if SpeechBrain is not installed or model
        download fails.
        """
        try:
            from speechbrain.inference.interfaces import foreign_class  # type: ignore[import]

            self._classifier = foreign_class(
                source=self._MODEL_SOURCE,
                pymodule_file="custom_interface.py",
                classname="CustomEncoderWav2vec2Classifier",
                savedir="/tmp/speechbrain_emotion",
            )
            self._ready = True
            logger.info("SpeechBrain emotion backend loaded from %s.", self._MODEL_SOURCE)
        except ImportError:
            logger.warning(
                "SpeechBrain is not installed.  Voice emotion analysis will be "
                "unavailable.  Install with: pip install speechbrain"
            )
            self._ready = False
        except Exception as exc:
            logger.warning("SpeechBrain warmup failed: %s", exc)
            self._ready = False

    def analyze_segment(self, audio_array: np.ndarray, sample_rate: int) -> dict:
        """Analyse a PCM audio segment for emotion.

        Args:
            audio_array: 1-D float32 array of PCM samples in [-1.0, 1.0].
            sample_rate: Sample rate in Hz.

        Returns:
            dict: Standardised voice emotion scores (see
                ``VoiceBackendInterface``).

        Raises:
            RuntimeError: If the backend is not ready.
        """
        if not self._ready or self._classifier is None:
            raise RuntimeError(
                "SpeechBrain backend is not ready.  Call warmup() first."
            )

        try:
            import torch  # type: ignore[import]

            # SpeechBrain expects a 2-D tensor [batch, time].
            waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
            lengths = torch.ones(1)

            out_probs, score, index, label = self._classifier.classify_batch(
                waveform, lengths
            )

            probs: list[float] = out_probs[0].tolist()
            # Pad / trim to the expected label set length.
            padded: list[float] = (probs + [0.0] * len(_EMOTION_LABELS))[
                : len(_EMOTION_LABELS)
            ]
            scores: dict[str, float] = {
                lbl: padded[i] for i, lbl in enumerate(_EMOTION_LABELS)
            }

            dominant_label: str = str(label[0]).lower()
            if dominant_label not in scores:
                dominant_label = max(scores, key=lambda k: scores[k])
            dominant_conf: float = float(score[0])

            # Rough arousal / valence heuristics.
            arousal: float = (
                scores.get("angry", 0.0)
                + scores.get("fearful", 0.0)
                + scores.get("stressed", 0.0)
                + scores.get("urgent", 0.0)
                + scores.get("happy", 0.0) * 0.5
            )
            valence: float = (
                scores.get("happy", 0.0)
                + scores.get("calm", 0.0) * 0.7
                - scores.get("sad", 0.0)
                - scores.get("angry", 0.0) * 0.5
            )
            # Clamp to [0, 1].
            arousal = min(max(arousal, 0.0), 1.0)
            valence = min(max(valence + 0.5, 0.0), 1.0)

            return {
                "dominant_emotion": dominant_label,
                "dominant_confidence": dominant_conf,
                "arousal": arousal,
                "valence": valence,
                "arousal_valid": True,
                "valence_valid": True,
                "neutral_score": scores.get("neutral", 0.0),
                "happy_score": scores.get("happy", 0.0),
                "sad_score": scores.get("sad", 0.0),
                "angry_score": scores.get("angry", 0.0),
                "fearful_score": scores.get("fearful", 0.0),
                "stressed_score": scores.get("stressed", 0.0),
                "calm_score": scores.get("calm", 0.0),
                "urgent_score": scores.get("urgent", 0.0),
                "confused_score": scores.get("confused", 0.0),
                "noisy_audio": False,
                "silence_detected": False,
                "model_failed": False,
                "backend_used": "speechbrain",
            }
        except Exception as exc:
            logger.warning("SpeechBrain inference failed: %s", exc)
            return self._failed_result(str(exc))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _failed_result(reason: str) -> dict:
        """Return a safe fallback dict indicating model failure.

        Args:
            reason: Short description of the failure.

        Returns:
            dict: Fallback result with model_failed=True.
        """
        return {
            "dominant_emotion": "neutral",
            "dominant_confidence": 0.0,
            "arousal": 0.0,
            "valence": 0.5,
            "arousal_valid": False,
            "valence_valid": False,
            "neutral_score": 0.0,
            "happy_score": 0.0,
            "sad_score": 0.0,
            "angry_score": 0.0,
            "fearful_score": 0.0,
            "stressed_score": 0.0,
            "calm_score": 0.0,
            "urgent_score": 0.0,
            "confused_score": 0.0,
            "noisy_audio": False,
            "silence_detected": False,
            "model_failed": True,
            "backend_used": "speechbrain",
        }

    @property
    def is_ready(self) -> bool:
        """Return True if SpeechBrain is loaded and ready for inference."""
        return self._ready
