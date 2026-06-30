"""Orchestrates all tracked PersonRecords across update cycles.

This is the single entry point the ROS2 node calls once per incoming
PersonStateArray. It is pure Python (no rclpy), deterministic given an
injected clock, and fully unit-testable.

Per-cycle algorithm
--------------------
1. Raw track_id continuity (cheap, the common case — most frames, the
   upstream detector's own track_id is unchanged).
2. For anything left unmatched: try re-identifying against TEMPORARILY_LOST
   records using ALL evidence (face, body, spatial proximity) — this is the
   "reappeared" path.
3. For anything still unmatched: try merging into currently-active records
   using ONLY strong evidence (face, body — never spatial proximity, which
   would risk merging two distinct, closely-spaced people who are both
   already being tracked). This handles raw-tracker ID churn without ever
   mixing two different individuals.
4. Anything still unmatched is a genuinely new person.
5. Everyone not matched this cycle is aged (may transition toward
   TEMPORARILY_LOST / LEFT_SCENE).
6. LEFT_SCENE records are reported exactly once (their final message) and
   then evicted — except candidates that were discarded without ever being
   confirmed, which are dropped silently (never published at all, mirroring
   the project's existing tentative-track convention).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from bonbon_multi_person_tracker.core.identity_associator import (
    AssociationCandidate,
    BodyReIDAssociator,
    FaceIdAssociator,
    IdentityAssociator,
)
from bonbon_multi_person_tracker.core.lifecycle_state_machine import (
    LifecycleConfig,
    PersonLifecycleState,
)
from bonbon_multi_person_tracker.core.person_record import PersonRecord, RawPersonDetection
from bonbon_multi_person_tracker.core.recall_buffer import RecallBuffer
from bonbon_multi_person_tracker.core.temporary_id_allocator import TemporaryIdAllocator

_CONFIRMED_STATES = (
    PersonLifecycleState.PRESENT,
    PersonLifecycleState.ACTIVE_INTERACTION,
    PersonLifecycleState.REAPPEARED,
)


class MultiPersonSceneManager:
    def __init__(
        self,
        lifecycle_config: LifecycleConfig | None = None,
        recall_window_sec: float = 300.0,
        max_persons: int = 20,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._lifecycle_config = lifecycle_config or LifecycleConfig()
        self._clock = clock or time.monotonic
        self._max_persons = max_persons

        self._records: dict[str, PersonRecord] = {}
        self._ever_confirmed: dict[str, bool] = {}
        self._allocator = TemporaryIdAllocator()
        self._recall = RecallBuffer(recall_window_sec=recall_window_sec, clock=self._clock)

        # ID-switch metric (evaluation-metrics audit, check #9): counts Pass 3
        # successes — every time the upstream raw tracker assigns a NEW
        # raw_track_id to someone who was already ACTIVE (not lost), which is
        # exactly the MOT-literature definition of an ID switch the system
        # caught and corrected via re-identification rather than spawning a
        # duplicate person. Pass 2 (reappearance after TEMPORARILY_LOST) is a
        # different metric — track re-acquisition after a real gap — and is
        # not counted here.
        self._id_switch_count = 0

        # Reappearance: full evidence, used only against TEMPORARILY_LOST.
        self._reappearance_associator = IdentityAssociator()
        # Tracker-churn merge against ACTIVE people: strong evidence only —
        # spatial proximity is deliberately excluded here (see module docstring).
        self._churn_associator = IdentityAssociator(
            strategies=[FaceIdAssociator(), BodyReIDAssociator()]
        )

    @property
    def active_person_count(self) -> int:
        return len(self._records)

    @property
    def recall_buffer_size(self) -> int:
        return len(self._recall)

    @property
    def id_switch_count(self) -> int:
        """Cumulative count of raw-tracker ID switches caught and corrected
        via re-identification against an ACTIVE person (see __init__)."""
        return self._id_switch_count

    def update(self, detections: list[RawPersonDetection]) -> list[PersonRecord]:
        matched: set[str] = set()

        # ── Pass 1: raw track_id continuity ──────────────────────────────────
        raw_id_index = {
            rec.raw_track_id: rec
            for rec in self._records.values()
            if rec.lifecycle_state != PersonLifecycleState.TEMPORARILY_LOST
        }
        unmatched: list[RawPersonDetection] = []
        for det in detections:
            rec = raw_id_index.get(det.raw_track_id)
            if rec is not None and rec.person_track_id not in matched:
                rec.apply_detection(det)
                rec.fsm.update(seen_this_cycle=True, match_confidence=1.0)
                matched.add(rec.person_track_id)
            else:
                unmatched.append(det)

        # ── Pass 2: reappearance against TEMPORARILY_LOST (full evidence) ──
        still_unmatched: list[RawPersonDetection] = []
        for det in unmatched:
            lost_pool = [
                r
                for r in self._records.values()
                if r.lifecycle_state == PersonLifecycleState.TEMPORARILY_LOST
                and r.person_track_id not in matched
            ]
            cand = AssociationCandidate(
                det.raw_track_id, det.face_id, det.x, det.y, det.z, det.body_embedding_id
            )
            result = self._reappearance_associator.associate(cand, lost_pool)
            if result.matched:
                rec = self._records[result.person_track_id]
                rec.apply_detection(det)
                rec.fsm.mark_reappeared(result.confidence)
                matched.add(rec.person_track_id)
            else:
                still_unmatched.append(det)

        # ── Pass 3: tracker-churn merge against ACTIVE people (strong evidence only) ─
        genuinely_new: list[RawPersonDetection] = []
        for det in still_unmatched:
            active_pool = [
                r
                for r in self._records.values()
                if r.lifecycle_state
                not in (PersonLifecycleState.TEMPORARILY_LOST, PersonLifecycleState.LEFT_SCENE)
                and r.person_track_id not in matched
            ]
            cand = AssociationCandidate(
                det.raw_track_id, det.face_id, det.x, det.y, det.z, det.body_embedding_id
            )
            result = self._churn_associator.associate(cand, active_pool)
            if result.matched:
                rec = self._records[result.person_track_id]
                rec.apply_detection(det)
                rec.fsm.update(seen_this_cycle=True, match_confidence=result.confidence)
                matched.add(rec.person_track_id)
                self._id_switch_count += 1
            else:
                genuinely_new.append(det)

        # ── Pass 4: genuinely new people (bounded) ──────────────────────────
        for det in genuinely_new:
            if len(self._records) >= self._max_persons:
                break
            person_track_id, temporary_person_id = self._allocator.allocate()
            rec = PersonRecord(
                person_track_id,
                temporary_person_id,
                det.raw_track_id,
                config=self._lifecycle_config,
                clock=self._clock,
            )
            rec.apply_detection(det)
            rec.fsm.update(seen_this_cycle=True, match_confidence=1.0)
            if not rec.known_person_id:
                recalled = self._recall.try_recall(det.face_id, det.body_embedding_id)
                if recalled:
                    rec.known_person_id = recalled
            self._records[person_track_id] = rec
            self._ever_confirmed[person_track_id] = False
            matched.add(person_track_id)

        # ── Pass 5: age everyone not matched this cycle ─────────────────────
        for rec in self._records.values():
            if rec.person_track_id not in matched:
                rec.fsm.update(seen_this_cycle=False)

        # Track "ever confirmed" so a never-confirmed candidate's eventual
        # LEFT_SCENE transition is dropped silently rather than published.
        for rec in self._records.values():
            if rec.lifecycle_state in _CONFIRMED_STATES:
                self._ever_confirmed[rec.person_track_id] = True

        # ── Pass 6: snapshot, then archive+evict LEFT_SCENE records ─────────
        snapshot: list[PersonRecord] = []
        to_evict: list[str] = []
        for rec in self._records.values():
            if rec.lifecycle_state == PersonLifecycleState.LEFT_SCENE:
                to_evict.append(rec.person_track_id)
                if self._ever_confirmed.get(rec.person_track_id):
                    snapshot.append(rec)  # final departure message
                if rec.known_person_id:
                    self._recall.remember(rec.known_person_id, rec.body_embedding_id)
            else:
                snapshot.append(rec)

        for ptid in to_evict:
            del self._records[ptid]
            self._ever_confirmed.pop(ptid, None)

        return snapshot

    def mark_active_interaction(self, person_track_id: str) -> bool:
        """External hook for bonbon_gesture / bonbon_speaker_intelligence to
        flag that this person is currently addressing the robot."""
        rec = self._records.get(person_track_id)
        if rec is None:
            return False
        rec.fsm.mark_active_interaction()
        return True
