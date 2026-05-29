"""
bonbon_gesture.logic.safety_classifier
=========================================
Classifies gesture events by their safety relevance for the BonBon robot.

Safety class vocabulary:
  'stop'    — robot must stop all motion immediately
  'alert'   — safety supervisor should be notified
  'approach' — robot may approach the person
  'retreat'  — robot should move away from the person
  'none'    — no safety relevance
"""

from __future__ import annotations

from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Classification tables
# ---------------------------------------------------------------------------

#: Mapping from gesture type to safety class string.
SAFETY_RELEVANT_GESTURES: Dict[str, str] = {
    "stop_palm": "stop",
    "raised_hand": "alert",
    "fallen_posture": "alert",
    "go_away": "retreat",
    "come_here": "approach",
}

#: Gestures that require an immediate robot response (bypass queuing).
IMMEDIATE_RESPONSE_GESTURES: frozenset = frozenset({"stop_palm", "fallen_posture"})


class GestureSafetyClassifier:
    """Classify a gesture for safety relevance.

    This classifier is stateless and its ``classify`` method can be called
    from any thread.
    """

    def classify(self, gesture: str) -> Tuple[bool, str, bool]:
        """Determine the safety classification of a gesture.

        Args:
            gesture: Gesture type string, e.g. ``'stop_palm'``.

        Returns:
            A 3-tuple ``(safety_relevant, safety_class, requires_immediate_response)``
            where:

            * *safety_relevant* (bool): True when the gesture has safety
              implications that the safety supervisor must handle.
            * *safety_class* (str): One of ``'stop'``, ``'alert'``,
              ``'approach'``, ``'retreat'``, or ``'none'``.
            * *requires_immediate_response* (bool): True when the gesture
              demands an immediate motor-safety action (bypasses normal
              event queuing).
        """
        if gesture in SAFETY_RELEVANT_GESTURES:
            safety_class = SAFETY_RELEVANT_GESTURES[gesture]
            requires_immediate = gesture in IMMEDIATE_RESPONSE_GESTURES
            return (True, safety_class, requires_immediate)
        return (False, "none", False)

    def is_safety_gesture(self, gesture: str) -> bool:
        """Convenience method — True when *gesture* is safety-relevant.

        Args:
            gesture: Gesture type string.

        Returns:
            True when the gesture has a safety classification.
        """
        return gesture in SAFETY_RELEVANT_GESTURES

    def requires_immediate(self, gesture: str) -> bool:
        """Convenience method — True when *gesture* needs an immediate response.

        Args:
            gesture: Gesture type string.

        Returns:
            True for stop_palm and fallen_posture.
        """
        return gesture in IMMEDIATE_RESPONSE_GESTURES
