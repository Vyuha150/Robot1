"""Classifies which body part produced the winning gesture.

GestureEvent.body_part needs to say whether a published gesture came from a
hand shape, an arm/body pose, the head, or a fallen/bent posture. The
pipeline's three classifiers are tried in sequence (hand -> body -> head, see
gesture_node._classify_and_publish) and the body classifier can either pass a
hand gesture straight through or override it with a pose-derived gesture —
this module makes that distinction explicit from the final winning label
rather than the node guessing.
"""

from __future__ import annotations

_HEAD_GESTURES = frozenset({"head_nod_yes", "head_shake_no"})
_POSTURE_GESTURES = frozenset({"fallen_posture", "fallen_or_bent_posture"})
_ARM_GESTURES = frozenset(
    {
        "raised_hand",
        "stop_palm",
        "wave",
        "come_here",
        "go_away",
        "pointing_left",
        "pointing_right",
        "pointing_forward",
        "pointing_at_object",
    }
)


def classify_body_part(final_gesture: str, hand_gesture: str) -> str:
    """Returns 'head' | 'posture' | 'arm' | 'hand' | '' (none/unknown).

    Args:
        final_gesture: The gesture label that ultimately won (after body and
            head classifiers have had a chance to override the raw hand
            classification).
        hand_gesture: The raw hand-classifier output for this frame, used to
            detect when the body classifier passed it through unchanged.
    """
    if final_gesture in _HEAD_GESTURES:
        return "head"
    if final_gesture in _POSTURE_GESTURES:
        return "posture"
    if final_gesture in _ARM_GESTURES:
        return "arm"
    if final_gesture == hand_gesture and hand_gesture not in ("none", "unknown_gesture", ""):
        return "hand"
    return ""
