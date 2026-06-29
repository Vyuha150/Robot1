"""Pure functions estimating engagement_level and urgency_level.

Grounded only in signals this system actually has — no invented gaze
tracking, no fabricated stress sensors. engagement_level is derived from
lifecycle state (does bonbon_multi_person_tracker think this person is
actively interacting?) plus speech/gesture recency. urgency_level is derived
from bonbon_affective_ai's own emotion classification (already computed,
reused not re-derived) and gesture safety-relevance (a signal affective_ai
never sees, since gesture and emotion are computed by separate packages).
"""

from __future__ import annotations

from bonbon_human_state_fusion.core.active_speaker_tracker import RECENTLY_SPOKE, SPEAKING

_ENGAGEMENT_BY_LIFECYCLE = {
    "new_candidate": 0.2,
    "present": 0.5,
    "active_interaction": 1.0,
    "temporarily_lost": 0.3,
    "reappeared": 0.6,
    "left_scene": 0.0,
}

# Mirrors HumanEmotionState.dominant_state's documented vocabulary
# (neutral,happy,confused,frustrated,angry,distressed,fearful,urgent,tired,
# engaged,disengaged) — only the states that plausibly indicate urgency.
_URGENT_EMOTIONAL_STATES = {
    "distressed": 0.9,
    "fearful": 0.85,
    "urgent": 1.0,
    "angry": 0.6,
    "frustrated": 0.4,
}


def estimate_engagement(
    lifecycle_state: str,
    active_speaker_status: str,
    has_recent_gesture: bool,
) -> float:
    """Returns 0.0 (not engaged) .. 1.0 (fully engaged)."""
    base = _ENGAGEMENT_BY_LIFECYCLE.get(lifecycle_state, 0.3)
    boost = 0.0
    if active_speaker_status == SPEAKING:
        boost += 0.3
    elif active_speaker_status == RECENTLY_SPOKE:
        boost += 0.1
    if has_recent_gesture:
        boost += 0.2
    return max(0.0, min(1.0, base + boost))


def estimate_urgency(
    emotional_state: str,
    gesture_requires_immediate_response: bool,
    text_emergency_detected: bool = False,
) -> float:
    """Returns 0.0 (routine) .. 1.0 (emergency).

    Never silently downgrades a strong signal: takes the MAX across
    available evidence rather than averaging (an emergency gesture must not
    be diluted by an unrelated calm emotional reading).
    """
    score = 0.0
    if gesture_requires_immediate_response:
        score = max(score, 1.0)
    if text_emergency_detected:
        score = max(score, 1.0)
    score = max(score, _URGENT_EMOTIONAL_STATES.get(emotional_state, 0.0))
    return score
