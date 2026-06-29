"""Links a speaker turn's audio direction-of-arrival to a visible person.

Same design pattern as bonbon_gesture's GesturePersonAssigner — nearest-match
within a tolerance, never a forced guess — applied to a different input
modality: here the bearing comes directly from the mic array's DOA reading
rather than being inferred from a camera-pixel position, so there's no
horizontal-frame-position conversion step needed.

Honest limitation: a single DOA reading describes the WHOLE utterance, not
each diarization segment within it (the mic array doesn't re-measure
direction per diarized sub-segment). So when an utterance has multiple
speakers (``is_overlapping`` from the caller), this module still returns its
best match but the caller should treat the association confidence as
reduced — it could be associating the wrong one of several overlapping
speakers to that bearing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TrackedPersonBearing:
    person_track_id: str
    bearing_deg: float


@dataclass
class AssociationOutcome:
    matched: bool
    person_track_id: str = ""
    confidence: float = 0.0


_UNKNOWN_DOA_DEG = -1.0


def associate_doa_to_person(
    doa_deg: float,
    tracked_persons: list[TrackedPersonBearing],
    max_bearing_delta_deg: float = 25.0,
) -> AssociationOutcome:
    """Finds the tracked person whose bearing is closest to *doa_deg*.

    Args:
        doa_deg: Direction-of-arrival for the utterance/segment. The
            ``-1.0`` sentinel (HAL "unknown" convention) never matches.
        tracked_persons: Currently-visible people with their bearings (from
            bonbon_multi_person_tracker's PersonTrack.position_3d).
        max_bearing_delta_deg: Maximum tolerated angular mismatch before the
            match is rejected rather than guessed.
    """
    if abs(doa_deg - _UNKNOWN_DOA_DEG) < 1e-6 or not tracked_persons:
        return AssociationOutcome(matched=False)

    best = None
    best_delta = math.inf
    for person in tracked_persons:
        delta = abs(_angle_diff(doa_deg, person.bearing_deg))
        if delta < best_delta:
            best, best_delta = person, delta

    if best is None or best_delta > max_bearing_delta_deg:
        return AssociationOutcome(matched=False)

    confidence = max(0.3, 1.0 - (best_delta / max_bearing_delta_deg) * 0.7)
    return AssociationOutcome(
        matched=True, person_track_id=best.person_track_id, confidence=confidence
    )


def _angle_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0
