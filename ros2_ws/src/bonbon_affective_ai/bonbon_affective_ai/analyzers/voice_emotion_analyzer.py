"""Voice emotion analyzer: wraps a backend and emits VoiceEmotion messages."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from ..backends.voice_backend_interface import VoiceBackendInterface
    from ..config.affective_config import AffectiveConfig
    from ..privacy.privacy_gate import PrivacyGate

logger = logging.getLogger(__name__)


class VoiceEmotionAnalyzer:
    """Processes buffered audio segments and emits ``VoiceEmotion`` messages.

    Responsibilities:
    - Validates that the audio segment meets the minimum length requirement.
    - Detects silence to avoid running the model on empty audio.
    - Respects privacy suppression from :class:`PrivacyGate`.
    - Builds and returns ``bonbon_msgs.msg.VoiceEmotion`` messages.

    This class performs no I/O and does not hold a ROS2 node reference.
    """

    _SILENCE_THRESHOLD: float = 1e-4  # RMS below this is considered silence

    def __init__(
        self,
        config: "AffectiveConfig",
        backend: "VoiceBackendInterface",
        privacy_gate: "PrivacyGate",
        node_clock,
    ) -> None:
        """Initialise the analyzer.

        Args:
            config: Active configuration dataclass.
            backend: Warmed-up voice emotion backend.
            privacy_gate: Gate controlling privacy suppression.
            node_clock: The ``node.get_clock()`` clock for message stamps.
        """
        self._config = config
        self._backend = backend
        self._privacy = privacy_gate
        self._clock = node_clock

    # ── Public interface ──────────────────────────────────────────────────────

    def analyze_segment(
        self,
        audio_array: np.ndarray,
        sample_rate: int,
        tracking_id: int = 0,
        person_id: str = "",
    ):
        """Analyse a PCM audio segment for tone-of-voice emotion.

        Returns None if the segment is too short or privacy suppression is
        active.

        Args:
            audio_array: 1-D float32 PCM array normalised to [-1.0, 1.0].
            sample_rate: Sample rate of the array in Hz.
            tracking_id: Optional tracking ID to associate with the result.
            person_id: Optional person identifier.

        Returns:
            Optional[VoiceEmotion]: Populated message, or None if skipped.
        """
        # Duration check.
        duration_sec: float = len(audio_array) / max(sample_rate, 1)
        if duration_sec < self._config.voice_segment_min_sec:
            return self._make_short_segment_msg(
                tracking_id, person_id, duration_sec
            )

        # Privacy gate.
        if self._privacy.should_suppress_voice():
            return self._make_suppressed_msg(tracking_id, person_id, duration_sec)

        # Silence detection.
        silence: bool = self._is_silence(audio_array)

        # Backend not ready.
        if not self._backend.is_ready:
            return self._make_failed_msg(tracking_id, person_id, duration_sec)

        try:
            result: dict = self._backend.analyze_segment(audio_array, sample_rate)
        except Exception as exc:
            logger.warning("Voice backend error: %s", exc)
            return self._make_failed_msg(tracking_id, person_id, duration_sec)

        result["silence_detected"] = silence or result.get("silence_detected", False)
        return self._build_msg(result, tracking_id, person_id, duration_sec)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_silence(self, audio_array: np.ndarray) -> bool:
        """Return True if the audio array is predominantly silent.

        Args:
            audio_array: PCM float array.

        Returns:
            bool: True when RMS amplitude is below the silence threshold.
        """
        if len(audio_array) == 0:
            return True
        rms: float = float(np.sqrt(np.mean(audio_array.astype(np.float64) ** 2)))
        return rms < self._SILENCE_THRESHOLD

    # ── Message builders ──────────────────────────────────────────────────────

    def _build_msg(
        self,
        data: dict,
        tracking_id: int,
        person_id: str,
        duration_sec: float,
    ):
        """Build a VoiceEmotion message from backend output.

        Args:
            data: Result dictionary from the voice backend.
            tracking_id: Integer tracking ID.
            person_id: String person identifier.
            duration_sec: Audio segment duration in seconds.

        Returns:
            VoiceEmotion: Populated ROS2 message.
        """
        from bonbon_msgs.msg import VoiceEmotion  # type: ignore[import]

        msg = VoiceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.voice"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.segment_duration_sec = float(duration_sec)

        msg.dominant_emotion = str(data.get("dominant_emotion", "neutral"))
        msg.dominant_confidence = float(data.get("dominant_confidence", 0.0))

        msg.arousal = float(data.get("arousal", 0.0))
        msg.valence = float(data.get("valence", 0.5))
        msg.arousal_valid = bool(data.get("arousal_valid", False))
        msg.valence_valid = bool(data.get("valence_valid", False))

        msg.neutral_score = float(data.get("neutral_score", 0.0))
        msg.happy_score = float(data.get("happy_score", 0.0))
        msg.sad_score = float(data.get("sad_score", 0.0))
        msg.angry_score = float(data.get("angry_score", 0.0))
        msg.fearful_score = float(data.get("fearful_score", 0.0))
        msg.stressed_score = float(data.get("stressed_score", 0.0))
        msg.calm_score = float(data.get("calm_score", 0.0))
        msg.urgent_score = float(data.get("urgent_score", 0.0))
        msg.confused_score = float(data.get("confused_score", 0.0))

        msg.noisy_audio = bool(data.get("noisy_audio", False))
        msg.silence_detected = bool(data.get("silence_detected", False))
        msg.short_segment = False
        msg.model_failed = bool(data.get("model_failed", False))
        msg.backend_used = str(data.get("backend_used", "unknown"))

        return msg

    def _make_short_segment_msg(self, tracking_id: int, person_id: str, duration_sec: float):
        """Return a VoiceEmotion message flagged as short_segment.

        Args:
            tracking_id: Integer tracking ID.
            person_id: String person identifier.
            duration_sec: Actual audio segment duration.

        Returns:
            VoiceEmotion: Message with short_segment=True.
        """
        from bonbon_msgs.msg import VoiceEmotion  # type: ignore[import]

        msg = VoiceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.voice"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.segment_duration_sec = float(duration_sec)
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.short_segment = True
        msg.model_failed = False
        msg.backend_used = "skipped"
        return msg

    def _make_suppressed_msg(
        self, tracking_id: int, person_id: str, duration_sec: float
    ):
        """Return a VoiceEmotion message flagged as suppressed by privacy.

        Args:
            tracking_id: Integer tracking ID.
            person_id: String person identifier.
            duration_sec: Audio segment duration.

        Returns:
            VoiceEmotion: Message with zeroed scores.
        """
        from bonbon_msgs.msg import VoiceEmotion  # type: ignore[import]

        msg = VoiceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.voice"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.segment_duration_sec = float(duration_sec)
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.short_segment = False
        msg.model_failed = False
        msg.backend_used = "suppressed"
        return msg

    def _make_failed_msg(
        self, tracking_id: int, person_id: str, duration_sec: float
    ):
        """Return a VoiceEmotion message indicating backend failure.

        Args:
            tracking_id: Integer tracking ID.
            person_id: String person identifier.
            duration_sec: Audio segment duration.

        Returns:
            VoiceEmotion: Message with model_failed=True.
        """
        from bonbon_msgs.msg import VoiceEmotion  # type: ignore[import]

        msg = VoiceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.voice"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.segment_duration_sec = float(duration_sec)
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.short_segment = False
        msg.model_failed = True
        msg.backend_used = "failed"
        return msg
