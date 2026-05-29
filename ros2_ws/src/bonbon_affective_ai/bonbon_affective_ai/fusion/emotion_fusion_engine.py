"""Multi-modal emotion fusion engine producing HumanEmotionState messages."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from ..config.affective_config import AffectiveConfig


# ── Mapping tables ────────────────────────────────────────────────────────────

EMOTION_TO_STATE: dict[str, str] = {
    "anger": "frustrated",
    "disgust": "frustrated",
    "fear": "fearful",
    "happiness": "happy",
    "sadness": "distressed",
    "surprise": "confused",
    "neutral": "neutral",
    "stressed": "distressed",
    "urgent": "urgent",
    "confused": "confused",
    "calm": "engaged",
    "happy": "happy",
    "angry": "frustrated",
    "sad": "distressed",
    "fearful": "fearful",
}

STATE_TO_RESPONSE_STYLE: dict[str, str] = {
    "neutral": "normal",
    "happy": "cheerful",
    "confused": "calm_supportive",
    "frustrated": "apologetic",
    "angry": "apologetic",
    "distressed": "calm_supportive",
    "fearful": "calm_supportive",
    "urgent": "emergency_clear",
    "tired": "concise",
    "engaged": "normal",
    "disengaged": "cheerful",
}

STATE_TO_DISTANCE: dict[str, float] = {
    "neutral": 1.0,
    "happy": 0.8,
    "confused": 1.0,
    "frustrated": 1.5,
    "angry": 2.0,
    "distressed": 1.2,
    "fearful": 1.5,
    "urgent": 0.8,
    "tired": 1.0,
    "engaged": 0.8,
    "disengaged": 1.0,
}

STATE_TO_TTS_EMOTION: dict[str, str] = {
    "neutral": "neutral",
    "happy": "happy",
    "confused": "gentle",
    "frustrated": "calm",
    "angry": "calm",
    "distressed": "gentle",
    "fearful": "gentle",
    "urgent": "urgent",
    "tired": "gentle",
    "engaged": "friendly",
    "disengaged": "friendly",
}

STATE_TO_PATIENCE: dict[str, float] = {
    "neutral": 1.0,
    "happy": 1.0,
    "confused": 2.0,
    "frustrated": 1.5,
    "angry": 1.5,
    "distressed": 2.0,
    "fearful": 2.0,
    "urgent": 0.5,
    "tired": 2.0,
    "engaged": 1.0,
    "disengaged": 1.0,
}


class EmotionFusionEngine:
    """Fuses face, voice, text, and gesture signals into a single HumanEmotionState.

    The fusion strategy is:
    1. Map raw emotion scores from each modality to a discrete state label.
    2. Apply weighted voting across available modalities.
    3. Override with emergency or distress signals if present in text or
       gesture — these always take priority over computed scores.
    4. Track per-person state history to determine stability.
    5. Populate all recommendation fields on the HumanEmotionState message.

    This class does not interact with ROS2 directly; the caller is responsible
    for stamping the output message and publishing it.
    """

    def __init__(self, config: AffectiveConfig) -> None:
        """Initialise the fusion engine with the given configuration.

        Args:
            config: Active ``AffectiveConfig`` providing fusion weights and
                stability window size.
        """
        self._config: AffectiveConfig = config
        # Per-person ring buffer of recent state labels.
        self._state_history: Dict[str, Deque[str]] = defaultdict(
            lambda: deque(maxlen=config.state_stability_window)
        )
        # Timestamps of the last state change per person.
        self._state_start_time: Dict[str, float] = {}
        self._previous_state: Dict[str, str] = {}
        self._state_change_count: Dict[str, int] = defaultdict(int)
        self._state_change_window: Dict[str, Deque[float]] = defaultdict(
            lambda: deque()
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def fuse(
        self,
        face,  # Optional[FaceEmotion]
        voice,  # Optional[VoiceEmotion]
        text,  # Optional[TextEmotion]
        gesture_state: str,
        person_id: str,
        tracking_id: int,
    ):
        """Produce a HumanEmotionState message from all available modalities.

        Args:
            face: Most recent ``FaceEmotion`` message for this person, or None.
            voice: Most recent ``VoiceEmotion`` message for this person, or None.
            text: Most recent ``TextEmotion`` message for this person, or None.
            gesture_state: Simplified gesture category string, e.g.
                'wave', 'stop_palm', 'fallen_posture', 'none'.
            person_id: Persistent string person identifier.
            tracking_id: Integer tracking frame ID.

        Returns:
            HumanEmotionState: Populated ROS2 message ready for publishing.
        """
        from bonbon_msgs.msg import HumanEmotionState  # type: ignore[import]

        now = time.time()
        msg = HumanEmotionState()
        msg.event_id = str(uuid.uuid4())
        msg.source_module = "bonbon_affective_ai.fusion"
        msg.person_id = person_id
        msg.tracking_id = tracking_id

        # ── Emergency / distress override ─────────────────────────────────────
        emergency: bool = False
        requires_alert: bool = False

        if text is not None:
            if text.emergency_detected:
                emergency = True
                requires_alert = True
            elif text.distress_detected or text.safety_concern_detected:
                requires_alert = True

        if gesture_state in ("fallen_posture", "stop_palm"):
            emergency = True
            requires_alert = True

        if emergency:
            dominant_state = "urgent"
            dominant_conf = 1.0
        else:
            dominant_state, dominant_conf = self._compute_weighted_state(
                face, voice, text, gesture_state
            )

        # ── Stability ─────────────────────────────────────────────────────────
        history = self._state_history[person_id]
        history.append(dominant_state)
        is_stable: bool = (
            len(history) >= self._config.state_stability_window
            and all(s == dominant_state for s in history)
        )

        # Track state duration.
        if person_id not in self._state_start_time:
            self._state_start_time[person_id] = now
        if self._previous_state.get(person_id) != dominant_state:
            self._state_start_time[person_id] = now
            if person_id in self._previous_state:
                self._state_change_count[person_id] += 1
                window_times = self._state_change_window[person_id]
                window_times.append(now)
                # Prune timestamps older than 60 s.
                while window_times and now - window_times[0] > 60.0:
                    window_times.popleft()

        previous_state: str = self._previous_state.get(person_id, "neutral")
        self._previous_state[person_id] = dominant_state
        state_duration_sec: int = int(now - self._state_start_time.get(person_id, now))
        change_count_60s: int = len(self._state_change_window[person_id])

        # ── Availability flags ────────────────────────────────────────────────
        face_avail = face is not None and not getattr(face, "privacy_suppressed", False)
        voice_avail = voice is not None and not getattr(voice, "model_failed", False)
        text_avail = text is not None
        gesture_avail = gesture_state not in ("none", "unknown", "")

        # ── Contribution scores (proportional to weight × confidence) ─────────
        face_contrib, voice_contrib, text_contrib, gesture_contrib = \
            self._contribution_scores(face, voice, text, gesture_state)

        # ── Populate message ──────────────────────────────────────────────────
        msg.dominant_state = dominant_state
        msg.dominant_confidence = float(dominant_conf)
        msg.is_stable = is_stable

        msg.face_contribution = float(face_contrib)
        msg.voice_contribution = float(voice_contrib)
        msg.text_contribution = float(text_contrib)
        msg.gesture_contribution = float(gesture_contrib)
        msg.face_available = face_avail
        msg.voice_available = voice_avail
        msg.text_available = text_avail
        msg.gesture_available = gesture_avail

        msg.recommended_response_style = STATE_TO_RESPONSE_STYLE.get(
            dominant_state, "normal"
        )
        msg.recommended_distance_m = float(
            STATE_TO_DISTANCE.get(dominant_state, 1.0)
        )
        msg.requires_operator_alert = requires_alert
        msg.suggested_tts_emotion = STATE_TO_TTS_EMOTION.get(
            dominant_state, "neutral"
        )
        msg.interaction_patience_multiplier = float(
            STATE_TO_PATIENCE.get(dominant_state, 1.0)
        )

        msg.state_duration_sec = state_duration_sec
        msg.state_change_count_last_60s = change_count_60s
        msg.previous_state = previous_state

        return msg

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_weighted_state(
        self,
        face,
        voice,
        text,
        gesture_state: str,
    ) -> Tuple[str, float]:
        """Compute dominant state via weighted voting across modalities.

        Args:
            face: FaceEmotion message or None.
            voice: VoiceEmotion message or None.
            text: TextEmotion message or None.
            gesture_state: Gesture category string.

        Returns:
            Tuple[str, float]: (dominant_state_label, confidence_in_0_1).
        """
        cfg = self._config
        state_votes: Dict[str, float] = defaultdict(float)

        # Face vote.
        if face is not None and not getattr(face, "privacy_suppressed", False):
            raw_emotion = getattr(face, "dominant_emotion", "neutral")
            conf = float(getattr(face, "dominant_confidence", 0.0))
            state = EMOTION_TO_STATE.get(raw_emotion, "neutral")
            state_votes[state] += cfg.fusion_face_weight * conf

        # Voice vote.
        if voice is not None and not getattr(voice, "model_failed", False):
            raw_emotion = getattr(voice, "dominant_emotion", "neutral")
            conf = float(getattr(voice, "dominant_confidence", 0.0))
            state = EMOTION_TO_STATE.get(raw_emotion, "neutral")
            state_votes[state] += cfg.fusion_voice_weight * conf

        # Text vote.
        if text is not None:
            raw_emotion = getattr(text, "dominant_emotion", "neutral")
            conf = float(getattr(text, "dominant_confidence", 0.0))
            state = EMOTION_TO_STATE.get(raw_emotion, "neutral")
            state_votes[state] += cfg.fusion_text_weight * conf

        # Gesture vote.
        if gesture_state not in ("none", "unknown", ""):
            g_state = self._gesture_to_state(gesture_state)
            state_votes[g_state] += cfg.fusion_gesture_weight * 0.8

        if not state_votes:
            return "neutral", 0.0

        dominant = max(state_votes, key=lambda s: state_votes[s])
        total_weight = sum(state_votes.values())
        confidence = state_votes[dominant] / total_weight if total_weight > 0 else 0.0
        return dominant, min(confidence, 1.0)

    def _contribution_scores(
        self,
        face,
        voice,
        text,
        gesture_state: str,
    ) -> Tuple[float, float, float, float]:
        """Compute normalised contribution values for each modality.

        Args:
            face: FaceEmotion or None.
            voice: VoiceEmotion or None.
            text: TextEmotion or None.
            gesture_state: Gesture category string.

        Returns:
            Tuple[float, float, float, float]:
                (face_contrib, voice_contrib, text_contrib, gesture_contrib)
        """
        cfg = self._config

        face_c: float = (
            cfg.fusion_face_weight * float(getattr(face, "dominant_confidence", 0.0))
            if face is not None and not getattr(face, "privacy_suppressed", False)
            else 0.0
        )
        voice_c: float = (
            cfg.fusion_voice_weight * float(getattr(voice, "dominant_confidence", 0.0))
            if voice is not None and not getattr(voice, "model_failed", False)
            else 0.0
        )
        text_c: float = (
            cfg.fusion_text_weight * float(getattr(text, "dominant_confidence", 0.0))
            if text is not None
            else 0.0
        )
        gesture_c: float = (
            cfg.fusion_gesture_weight * 0.8
            if gesture_state not in ("none", "unknown", "")
            else 0.0
        )

        total = face_c + voice_c + text_c + gesture_c
        if total < 1e-9:
            return 0.0, 0.0, 0.0, 0.0
        return face_c / total, voice_c / total, text_c / total, gesture_c / total

    @staticmethod
    def _gesture_to_state(gesture_type: str) -> str:
        """Map a gesture type string to a human state label.

        Args:
            gesture_type: Gesture type as used in GestureEvent.gesture_type.

        Returns:
            str: Mapped state label.
        """
        mapping: dict[str, str] = {
            "wave": "engaged",
            "raised_hand": "engaged",
            "stop_palm": "urgent",
            "pointing_left": "engaged",
            "pointing_right": "engaged",
            "pointing_forward": "engaged",
            "thumbs_up": "happy",
            "thumbs_down": "frustrated",
            "come_here": "engaged",
            "go_away": "frustrated",
            "head_nod_yes": "engaged",
            "head_shake_no": "frustrated",
            "fallen_posture": "urgent",
        }
        return mapping.get(gesture_type, "neutral")
