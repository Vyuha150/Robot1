"""
bonbon_gesture.logic.intent_mapper
====================================
Maps raw gesture type strings to high-level robot intents.

The intent string is designed to be consumed by the BonBon behaviour layer
and LLM planner without requiring them to know the raw gesture vocabulary.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Mapping table
# ---------------------------------------------------------------------------

GESTURE_TO_INTENT: Dict[str, str] = {
    "wave": "greeting_request",
    "raised_hand": "attention_request",
    "stop_palm": "stop_request",
    "pointing_left": "direction_left",
    "pointing_right": "direction_right",
    "pointing_forward": "direction_forward",
    "thumbs_up": "positive_confirmation",
    "thumbs_down": "negative_confirmation",
    "come_here": "approach_request",
    "go_away": "retreat_request",
    "head_nod_yes": "yes_confirmation",
    "head_shake_no": "no_confirmation",
    "fallen_posture": "emergency_alert",
    "unknown_gesture": "unknown",
    "none": "none",
}


class GestureIntentMapper:
    """Map gesture type strings to robot intent labels.

    Uses a static lookup table.  Gestures not in the table are mapped to
    ``'unknown'``.
    """

    def get_intent(self, gesture: str) -> str:
        """Return the robot intent corresponding to *gesture*.

        Args:
            gesture: A gesture type string, e.g. ``'raised_hand'``.

        Returns:
            An intent string, e.g. ``'attention_request'``.  Returns
            ``'unknown'`` for any gesture not in the mapping table.
        """
        return GESTURE_TO_INTENT.get(gesture, "unknown")

    def all_intents(self) -> Dict[str, str]:
        """Return a copy of the complete gesture→intent mapping table.

        Returns:
            Dictionary mapping gesture names to intent strings.
        """
        return dict(GESTURE_TO_INTENT)
