"""Mutable per-person tracking record + the raw per-cycle detection input shape."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bonbon_multi_person_tracker.core.lifecycle_state_machine import (
    LifecycleConfig,
    PersonLifecycleFSM,
)


@dataclass
class RawPersonDetection:
    """One person detection for the current cycle, built from PersonState."""

    raw_track_id: str
    face_id: str = ""
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    face_bbox: tuple[int, int, int, int] | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    body_embedding_id: str = ""
    face_embedding_id: str = ""


class PersonRecord:
    """Everything bonbon_multi_person_tracker knows about one person.

    Wraps a :class:`PersonLifecycleFSM` (identity-lifecycle state) with the
    visual/spatial evidence needed to build a ``PersonTrack`` message.
    """

    def __init__(
        self,
        person_track_id: str,
        temporary_person_id: str,
        raw_track_id: str,
        config: LifecycleConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.person_track_id = person_track_id
        self.temporary_person_id = temporary_person_id
        self.known_person_id = ""
        self.raw_track_id = raw_track_id

        self.bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.face_bbox: tuple[int, int, int, int] | None = None
        self.body_embedding_id = ""
        self.face_embedding_id = ""

        self.last_x = 0.0
        self.last_y = 0.0
        self.last_z = 0.0
        self.vx = 0.0
        self.vy = 0.0

        self.fsm = PersonLifecycleFSM(person_track_id, config=config, clock=clock)

    # ── Convenience passthroughs used by IdentityAssociator (Protocol match) ─

    @property
    def known_face_id(self) -> str:
        return self.known_person_id

    @property
    def time_since_last_seen_sec(self) -> float:
        return self.fsm.time_since_last_seen_sec

    @property
    def lifecycle_state(self):
        return self.fsm.state

    @property
    def confidence(self) -> float:
        return self.fsm.confidence

    def apply_detection(self, det: RawPersonDetection) -> None:
        """Copy fresh evidence from a matched detection onto this record."""
        self.raw_track_id = det.raw_track_id
        self.bbox = det.bbox
        self.face_bbox = det.face_bbox
        if det.face_id:
            self.known_person_id = det.face_id
        if det.body_embedding_id:
            self.body_embedding_id = det.body_embedding_id
        if det.face_embedding_id:
            self.face_embedding_id = det.face_embedding_id

        dt = max(self.fsm.time_since_last_seen_sec, 1.0 / 30.0)
        self.vx = (det.x - self.last_x) / dt
        self.vy = (det.y - self.last_y) / dt
        self.last_x, self.last_y, self.last_z = det.x, det.y, det.z
