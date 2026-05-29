"""EmotionAwareResponsePlanner — selects appropriate robot responses based on emotion.

Given a fused HumanEmotionState, this planner determines:
  - Which gesture the robot should perform
  - What TTS emotion/style to use
  - How urgent the behavioral response should be

The planner uses a lookup table strategy — no LLM, deterministic, < 1 ms.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

_logger = logging.getLogger(__name__)


@dataclass
class ResponsePlan:
    """A planned robot response to a human emotional state."""

    gesture_name: str
    """Gesture to perform (empty = no gesture change)."""

    tts_emotion: str
    """TTS emotion parameter: 'neutral', 'warm', 'concerned', 'urgent', 'calm'."""

    tts_speed_scale: float
    """TTS speed multiplier: 0.8=slow, 1.0=normal, 1.2=slightly_fast."""

    urgency: float
    """0.0=no rush, 1.0=immediate response needed."""

    acknowledgment_text: str
    """Optional short acknowledgment phrase for TTS."""

    reason: str = ""
    """Why this plan was selected."""


# Emotion → response mapping table.
# Keys are the canonical emotion labels from bonbon_affective_ai.
_EMOTION_PLANS: Dict[str, ResponsePlan] = {
    "happy": ResponsePlan(
        gesture_name="wave",
        tts_emotion="warm",
        tts_speed_scale=1.0,
        urgency=0.1,
        acknowledgment_text="",
        reason="Positive emotion detected — respond warmly.",
    ),
    "neutral": ResponsePlan(
        gesture_name="listening_pose",
        tts_emotion="neutral",
        tts_speed_scale=1.0,
        urgency=0.1,
        acknowledgment_text="",
        reason="Neutral state — maintain attentive pose.",
    ),
    "sad": ResponsePlan(
        gesture_name="listening_pose",
        tts_emotion="warm",
        tts_speed_scale=0.9,
        urgency=0.3,
        acknowledgment_text="I'm here to help.",
        reason="Sadness detected — slow down, be warm.",
    ),
    "angry": ResponsePlan(
        gesture_name="listening_pose",
        tts_emotion="calm",
        tts_speed_scale=0.85,
        urgency=0.5,
        acknowledgment_text="I understand. Let me help you.",
        reason="Anger detected — deescalate with calm slow speech.",
    ),
    "fearful": ResponsePlan(
        gesture_name="rest_pose",
        tts_emotion="calm",
        tts_speed_scale=0.8,
        urgency=0.6,
        acknowledgment_text="You're safe. I'm here.",
        reason="Fear detected — retreat, be very calm.",
    ),
    "surprised": ResponsePlan(
        gesture_name="thinking_pose",
        tts_emotion="neutral",
        tts_speed_scale=0.9,
        urgency=0.2,
        acknowledgment_text="",
        reason="Surprise detected — pause and listen.",
    ),
    "disgusted": ResponsePlan(
        gesture_name="rest_pose",
        tts_emotion="neutral",
        tts_speed_scale=1.0,
        urgency=0.2,
        acknowledgment_text="",
        reason="Disgust detected — maintain neutral distance.",
    ),
    "distressed": ResponsePlan(
        gesture_name="listening_pose",
        tts_emotion="concerned",
        tts_speed_scale=0.85,
        urgency=0.8,
        acknowledgment_text="Are you alright? Do you need help?",
        reason="Distress detected — express concern, offer help.",
    ),
    "emergency": ResponsePlan(
        gesture_name="emergency_attention_pose",
        tts_emotion="urgent",
        tts_speed_scale=1.2,
        urgency=1.0,
        acknowledgment_text="Emergency detected! Alerting staff now.",
        reason="Emergency state — maximum urgency.",
    ),
}

_DEFAULT_PLAN = ResponsePlan(
    gesture_name="listening_pose",
    tts_emotion="neutral",
    tts_speed_scale=1.0,
    urgency=0.1,
    acknowledgment_text="",
    reason="Default plan — unknown emotion.",
)

# Operating mode adjustments
_MODE_GESTURE_OVERRIDE: Dict[str, str] = {
    "child_safe": "greeting_pose",
    "elderly":    "listening_pose",
    "demo":       "wave",
}
_MODE_SPEED_OVERRIDE: Dict[str, float] = {
    "child_safe": 0.85,
    "elderly":    0.8,
}


class EmotionAwareResponsePlanner:
    """Select an appropriate robot response based on fused emotion state.

    Usage::

        planner = EmotionAwareResponsePlanner()
        plan = planner.plan(dominant_emotion="sad", operating_mode="normal")
        # plan.gesture_name → 'listening_pose'
        # plan.tts_emotion  → 'warm'
    """

    def plan(
        self,
        dominant_emotion: str,
        emotion_confidence: float = 1.0,
        operating_mode: str = "normal",
        is_emergency: bool = False,
        has_emergency_keyword: bool = False,
    ) -> ResponsePlan:
        """Produce a :class:`ResponsePlan` for the given emotional context.

        Args:
            dominant_emotion: Primary emotion label (e.g. 'sad', 'angry').
            emotion_confidence: Confidence in the emotion label [0, 1].
            operating_mode: Current operating mode ('normal', 'child_safe', etc.).
            is_emergency: True when the safety supervisor is in emergency state.
            has_emergency_keyword: True when emergency keywords were detected in speech.

        Returns:
            A :class:`ResponsePlan` with gesture, TTS and urgency fields.
        """
        # Emergency overrides everything
        if is_emergency or has_emergency_keyword:
            plan = _EMOTION_PLANS.get("emergency", _DEFAULT_PLAN)
            _logger.warning("EmotionResponsePlanner: EMERGENCY response selected.")
            return plan

        # Low confidence → fallback to neutral
        if emotion_confidence < 0.35:
            _logger.debug(
                "Low confidence (%.2f) for emotion '%s' — using neutral plan.",
                emotion_confidence, dominant_emotion,
            )
            base = _EMOTION_PLANS["neutral"]
        else:
            base = _EMOTION_PLANS.get(dominant_emotion.lower(), _DEFAULT_PLAN)

        # Apply operating mode overrides
        gesture = _MODE_GESTURE_OVERRIDE.get(operating_mode, base.gesture_name)
        speed   = _MODE_SPEED_OVERRIDE.get(operating_mode, base.tts_speed_scale)

        return ResponsePlan(
            gesture_name=gesture,
            tts_emotion=base.tts_emotion,
            tts_speed_scale=speed,
            urgency=base.urgency,
            acknowledgment_text=base.acknowledgment_text,
            reason=base.reason,
        )

    def all_supported_emotions(self) -> list:
        """Return list of emotion labels this planner has explicit mappings for."""
        return list(_EMOTION_PLANS.keys())
