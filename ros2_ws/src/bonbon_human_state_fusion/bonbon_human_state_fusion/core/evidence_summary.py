"""Builds the human-readable evidence_summary string for HumanState.

Explainability requirement from the project brief: "explain evidence."
Operators and debugging should be able to see WHICH modalities contributed
and why a confidence/state was reached, not just the final numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvidenceInputs:
    known_person_id: str
    lifecycle_state: str
    emotional_state: str
    emotional_state_source: str  # "" if unavailable, else e.g. "bonbon_affective_ai"
    current_gesture: str
    gesture_age_sec: float | None
    active_speaker_status: str
    has_transcript: bool


def build_evidence_summary(ev: EvidenceInputs) -> str:
    parts: list[str] = []

    identity = f"known ({ev.known_person_id})" if ev.known_person_id else "unidentified"
    parts.append(f"identity: {identity}")
    parts.append(f"lifecycle: {ev.lifecycle_state}")

    if ev.emotional_state_source:
        parts.append(f"emotion: {ev.emotional_state} ({ev.emotional_state_source})")
    else:
        parts.append("emotion: unavailable")

    if ev.current_gesture and ev.current_gesture not in ("none", "unknown", "unknown_gesture"):
        if ev.gesture_age_sec is not None:
            parts.append(f"gesture: {ev.current_gesture} ({ev.gesture_age_sec:.1f}s ago)")
        else:
            parts.append(f"gesture: {ev.current_gesture}")
    else:
        parts.append("gesture: none")

    speech = f"{ev.active_speaker_status}"
    if ev.has_transcript:
        speech += ", transcript available"
    parts.append(f"speech: {speech}")

    return " | ".join(parts)
