"""Face emotion analyzer: wraps a backend and applies temporal smoothing."""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Dict, Optional

import numpy as np

from ..fusion.temporal_smoother import TemporalSmoother

if TYPE_CHECKING:
    from ..backends.face_backend_interface import FaceBackendInterface
    from ..config.affective_config import AffectiveConfig
    from ..privacy.privacy_gate import PrivacyGate

logger = logging.getLogger(__name__)


class FaceEmotionAnalyzer:
    """Processes face crop images and emits ``FaceEmotion`` messages.

    Responsibilities:
    - Rate-limits calls to the backend per tracking ID using
      ``face_sample_interval_sec``.
    - Applies temporal smoothing via :class:`TemporalSmoother`.
    - Respects privacy suppression from :class:`PrivacyGate`.
    - Builds and returns ``bonbon_msgs.msg.FaceEmotion`` messages ready for
      publishing by the calling node.

    This class performs no I/O and does not hold a ROS2 node reference;
    it is intended to be called from within a ``ThreadPoolExecutor`` task to
    keep the ROS2 executor thread free.
    """

    def __init__(
        self,
        config: "AffectiveConfig",
        backend: "FaceBackendInterface",
        privacy_gate: "PrivacyGate",
        node_clock,  # rclpy.clock.Clock – used for ROS timestamps
    ) -> None:
        """Initialise the analyzer.

        Args:
            config: Active configuration dataclass.
            backend: Warmed-up face emotion backend.
            privacy_gate: Gate controlling privacy suppression.
            node_clock: The ``node.get_clock()`` clock for message stamps.
        """
        self._config = config
        self._backend = backend
        self._privacy = privacy_gate
        self._clock = node_clock
        self._last_sample_time: Dict[str, float] = {}
        self._smoother = TemporalSmoother(window=config.face_temporal_window)

    # ── Public interface ──────────────────────────────────────────────────────

    def analyze_face_crop(
        self,
        face_img: np.ndarray,
        tracking_id: int,
        person_id: str,
    ):
        """Analyse a face crop image for the given person.

        Rate-limits calls per tracking ID.  Returns None if the interval has
        not elapsed since the last sample for this person.

        Args:
            face_img: BGR numpy array of the face crop, shape (H, W, 3).
            tracking_id: Integer tracking ID from the vision system.
            person_id: String person identifier (from ``PersonState.track_id``).

        Returns:
            Optional[FaceEmotion]: A populated message, or None if the sample
                interval has not elapsed.
        """
        now: float = time.monotonic()
        key: str = str(tracking_id)

        # Rate-limit per tracking ID.
        if now - self._last_sample_time.get(key, 0.0) < self._config.face_sample_interval_sec:
            return None

        self._last_sample_time[key] = now

        # Privacy gate.
        if self._privacy.should_suppress_face():
            return self._make_suppressed_msg(tracking_id, person_id)

        # Backend not ready — mark as failed rather than crashing.
        if not self._backend.is_ready:
            return self._make_failed_msg(tracking_id, person_id)

        try:
            raw: dict = self._backend.analyze(face_img)
        except Exception as exc:
            logger.warning("Face backend error for tracking_id=%d: %s", tracking_id, exc)
            return self._make_failed_msg(tracking_id, person_id)

        smoothed: dict = self._smoother.smooth(tracking_id, raw)
        return self._build_msg(smoothed, tracking_id, person_id)

    def reset_tracking_id(self, tracking_id: int) -> None:
        """Remove cached state for a tracking ID that has left the scene.

        Args:
            tracking_id: The tracking ID to evict.
        """
        key = str(tracking_id)
        self._last_sample_time.pop(key, None)
        self._smoother.reset(tracking_id)

    # ── Message builders ──────────────────────────────────────────────────────

    def _build_msg(self, data: dict, tracking_id: int, person_id: str):
        """Build a fully-populated FaceEmotion message from smoothed scores.

        Args:
            data: Smoothed emotion score dictionary.
            tracking_id: Integer tracking ID.
            person_id: String person identifier.

        Returns:
            FaceEmotion: Populated ROS2 message.
        """
        from bonbon_msgs.msg import FaceEmotion  # type: ignore[import]

        msg = FaceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.face"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)

        msg.anger = float(data.get("anger", 0.0))
        msg.disgust = float(data.get("disgust", 0.0))
        msg.fear = float(data.get("fear", 0.0))
        msg.happiness = float(data.get("happiness", 0.0))
        msg.sadness = float(data.get("sadness", 0.0))
        msg.surprise = float(data.get("surprise", 0.0))
        msg.neutral = float(data.get("neutral", 0.0))

        msg.dominant_emotion = str(data.get("dominant_emotion", "neutral"))
        msg.dominant_confidence = float(data.get("dominant_confidence", 0.0))
        msg.is_ambiguous = (
            msg.dominant_confidence < self._config.face_confidence_threshold
        )
        msg.low_quality_input = False
        msg.privacy_suppressed = False
        msg.privacy_level = self._privacy.current_level

        return msg

    def _make_suppressed_msg(self, tracking_id: int, person_id: str):
        """Build a FaceEmotion message with privacy_suppressed=True.

        Args:
            tracking_id: Integer tracking ID.
            person_id: String person identifier.

        Returns:
            FaceEmotion: Message with all emotion scores zeroed and
                privacy_suppressed flag set.
        """
        from bonbon_msgs.msg import FaceEmotion  # type: ignore[import]

        msg = FaceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.face"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.is_ambiguous = True
        msg.privacy_suppressed = True
        msg.privacy_level = self._privacy.current_level
        return msg

    def _make_failed_msg(self, tracking_id: int, person_id: str):
        """Build a FaceEmotion message indicating backend failure.

        Args:
            tracking_id: Integer tracking ID.
            person_id: String person identifier.

        Returns:
            FaceEmotion: Message with low_quality_input=True.
        """
        from bonbon_msgs.msg import FaceEmotion  # type: ignore[import]

        msg = FaceEmotion()
        msg.header.stamp = self._clock.now().to_msg()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.face"
        msg.tracking_id = int(tracking_id)
        msg.person_id = str(person_id)
        msg.dominant_emotion = "neutral"
        msg.dominant_confidence = 0.0
        msg.is_ambiguous = True
        msg.low_quality_input = True
        msg.privacy_suppressed = False
        msg.privacy_level = self._privacy.current_level
        return msg
