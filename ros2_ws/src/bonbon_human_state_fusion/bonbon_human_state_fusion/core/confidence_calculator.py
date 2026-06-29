"""Computes HumanState.confidence — explicitly NOT an average.

Per the project brief ("preserve uncertainty"): a person with only one
available modality (say, just identity/lifecycle) must report markedly
lower confidence than a person with four modalities all agreeing, even if
that one modality itself reports high confidence. A naive average of
available scores would hide that — two available high-confidence readings
would look identical to four, when in fact the two-reading case has covered
half as much evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

_TOTAL_MODALITIES = 4  # lifecycle, emotion, gesture, speech


@dataclass
class ConfidenceInputs:
    lifecycle_confidence: float  # always available (from PersonTrack)
    emotion_confidence: float | None  # None if no HumanEmotionState bridged
    gesture_confidence: float | None  # None if no recent gesture
    speech_confidence: float | None  # None if no recent transcript


def compute_confidence(inputs: ConfidenceInputs) -> float:
    available = [inputs.lifecycle_confidence]
    if inputs.emotion_confidence is not None:
        available.append(inputs.emotion_confidence)
    if inputs.gesture_confidence is not None:
        available.append(inputs.gesture_confidence)
    if inputs.speech_confidence is not None:
        available.append(inputs.speech_confidence)

    avg = sum(available) / len(available)
    coverage = len(available) / _TOTAL_MODALITIES
    # Scales the average down by coverage, but never below half — even a
    # single confident modality is still meaningful evidence, just not
    # complete evidence.
    return avg * (0.5 + 0.5 * coverage)
