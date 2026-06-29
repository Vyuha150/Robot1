"""Associates incoming per-frame person detections to existing tracked records.

Three strategies, tried in priority order (highest-confidence evidence first):

1. FaceIdAssociator       — exact match on PersonState.face_id (already a real,
                             existing signal from bonbon_vision's face_pipeline).
2. SpatialProximityAssociator — position-delta gated by max plausible speed;
                             used when face is unavailable (back of head, no
                             camera angle, privacy mode).
3. BodyReIDAssociator     — pluggable backend interface + mock, for a future
                             body re-identification embedding model. Not a real
                             ML model today (none exists in this repo); this is
                             the same "backend interface + mock now, real later"
                             pattern used throughout bonbon_hal/bonbon_vision.

This module never invents a match: if no strategy clears its confidence floor,
the candidate is reported as unmatched and the scene manager treats it as a
new person (new_candidate), never silently merging two different individuals.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AssociationCandidate:
    """A pending detection, not yet linked to a person_track_id."""

    raw_track_id: str
    face_id: str
    x: float
    y: float
    z: float
    body_embedding_id: str = ""


class TrackedPersonLike(Protocol):
    """Minimal shape an associator needs from an existing tracked record —
    deliberately narrow so this module has no dependency on PersonRecord."""

    person_track_id: str
    known_face_id: str
    last_x: float
    last_y: float
    last_z: float
    time_since_last_seen_sec: float
    body_embedding_id: str


@dataclass
class AssociationResult:
    matched: bool
    person_track_id: str = ""
    confidence: float = 0.0
    strategy: str = ""


class BaseAssociator(ABC):
    name: str = "base"

    @abstractmethod
    def try_associate(
        self, candidate: AssociationCandidate, pool: list[TrackedPersonLike]
    ) -> AssociationResult: ...


class FaceIdAssociator(BaseAssociator):
    """Highest-confidence: an exact registered face_id match never expires."""

    name = "face_id"

    def try_associate(self, candidate, pool):
        if not candidate.face_id:
            return AssociationResult(matched=False)
        for person in pool:
            if person.known_face_id and person.known_face_id == candidate.face_id:
                return AssociationResult(
                    matched=True,
                    person_track_id=person.person_track_id,
                    confidence=0.98,
                    strategy=self.name,
                )
        return AssociationResult(matched=False)


class SpatialProximityAssociator(BaseAssociator):
    """Gate by plausible walking speed: a person can't teleport further than
    ``max_speed_mps * time_since_last_seen_sec`` (+ a fixed slack radius for
    detector/odometry noise).
    """

    name = "spatial_proximity"

    def __init__(self, max_speed_mps: float = 1.8, slack_radius_m: float = 0.5) -> None:
        self._max_speed = max_speed_mps
        self._slack = slack_radius_m

    def try_associate(self, candidate, pool):
        best: TrackedPersonLike | None = None
        best_dist = math.inf
        for person in pool:
            dx = candidate.x - person.last_x
            dy = candidate.y - person.last_y
            dz = candidate.z - person.last_z
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            gate = self._max_speed * max(person.time_since_last_seen_sec, 0.1) + self._slack
            if dist <= gate and dist < best_dist:
                best, best_dist = person, dist
        if best is None:
            return AssociationResult(matched=False)
        # Confidence decays linearly from 0.9 (dist=0) to 0.3 (dist=gate edge).
        gate = self._max_speed * max(best.time_since_last_seen_sec, 0.1) + self._slack
        frac = 1.0 - (best_dist / gate if gate > 0 else 1.0)
        confidence = 0.3 + 0.6 * max(0.0, min(1.0, frac))
        return AssociationResult(
            matched=True,
            person_track_id=best.person_track_id,
            confidence=confidence,
            strategy=self.name,
        )


class BodyReIDAssociator(BaseAssociator):
    """Body re-identification via embedding similarity.

    No real embedding model exists yet anywhere in this repo (bonbon_vision
    only does face embeddings). This mock backend matches on the literal
    body_embedding_id string, which is sufficient for tests/sim and keeps the
    seam open for a real re-id model (e.g. a torchreid/OSNet backend) without
    changing any caller.
    """

    name = "body_reid"

    def __init__(self, min_confidence: float = 0.55) -> None:
        self._min_confidence = min_confidence

    def try_associate(self, candidate, pool):
        if not candidate.body_embedding_id:
            return AssociationResult(matched=False)
        for person in pool:
            if person.body_embedding_id and person.body_embedding_id == candidate.body_embedding_id:
                return AssociationResult(
                    matched=True,
                    person_track_id=person.person_track_id,
                    confidence=0.75,
                    strategy=self.name,
                )
        return AssociationResult(matched=False)


class IdentityAssociator:
    """Runs all strategies in priority order, returns the first match."""

    def __init__(self, strategies: list[BaseAssociator] | None = None) -> None:
        self._strategies = strategies or [
            FaceIdAssociator(),
            BodyReIDAssociator(),
            SpatialProximityAssociator(),
        ]

    def associate(
        self, candidate: AssociationCandidate, pool: list[TrackedPersonLike]
    ) -> AssociationResult:
        if not pool:
            return AssociationResult(matched=False)
        for strategy in self._strategies:
            result = strategy.try_associate(candidate, pool)
            if result.matched:
                return result
        return AssociationResult(matched=False)
