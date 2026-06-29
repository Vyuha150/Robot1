"""Per-person lifecycle state machine.

This is the heart of bonbon_multi_person_tracker: it answers "is this still the
same person, and what is their current lifecycle state" — something none of the
three pre-existing trackers in this repo do (they either evict on first miss, or
have no re-identification concept at all).

States
------
NEW_CANDIDATE      — seen, but not yet confirmed (avoids one-frame false positives)
PRESENT            — confirmed, detected in the current cycle
ACTIVE_INTERACTION — present AND currently speaking/gesturing/addressed
                     (set via an external hook — this FSM does not itself know
                     about gestures or speech; gesture/speaker packages call
                     ``mark_active_interaction()``)
TEMPORARILY_LOST   — missed this cycle, but within the loss-grace window
REAPPEARED         — one-shot: re-matched after TEMPORARILY_LOST. Exists for
                     exactly one update so consumers can react to "they're back"
                     before it auto-collapses to PRESENT.
LEFT_SCENE         — terminal. Grace window expired. One final message is
                     produced for this person_track_id, then the record is
                     dropped from active tracking (see RecallBuffer in
                     multi_person_scene_manager.py for "same known person,
                     new temporary profile" handling on a later return).

Hard rule (explicit in the project brief): never declare a person gone from one
missed frame. A miss always goes PRESENT/ACTIVE_INTERACTION -> TEMPORARILY_LOST
first; LEFT_SCENE only fires after ``loss_grace_sec`` of continuous absence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class PersonLifecycleState(StrEnum):
    NEW_CANDIDATE = "new_candidate"
    PRESENT = "present"
    ACTIVE_INTERACTION = "active_interaction"
    TEMPORARILY_LOST = "temporarily_lost"
    REAPPEARED = "reappeared"
    LEFT_SCENE = "left_scene"


@dataclass
class LifecycleConfig:
    """Tunable timeouts/thresholds for the lifecycle FSM.

    Attributes:
        confirmation_hits: consecutive "seen" cycles required for
            NEW_CANDIDATE -> PRESENT.
        candidate_miss_limit: consecutive "missed" cycles while still a
            NEW_CANDIDATE before the record is discarded (never published).
        loss_grace_sec: how long a TEMPORARILY_LOST person may stay missing
            before transitioning to LEFT_SCENE.
        active_interaction_hold_sec: how long ACTIVE_INTERACTION persists
            after the last ``mark_active_interaction()`` call before decaying
            to PRESENT.
        confidence_decay_per_sec: confidence lost per second while
            TEMPORARILY_LOST (floor at 0.05 — never fully zero so a late
            re-match is still possible).
    """

    confirmation_hits: int = 2
    candidate_miss_limit: int = 2
    loss_grace_sec: float = 4.0
    active_interaction_hold_sec: float = 3.0
    confidence_decay_per_sec: float = 0.15


@dataclass
class LifecycleTransition:
    """A single state change, for diagnostics / lifecycle-event publishing."""

    person_track_id: str
    from_state: PersonLifecycleState | None
    to_state: PersonLifecycleState
    reason: str
    timestamp: float


class PersonLifecycleFSM:
    """Owns the lifecycle state for ONE person across update cycles.

    Args:
        person_track_id: the stable identity key this FSM tracks.
        config: timeout/threshold configuration.
        clock: injectable monotonic clock (seconds) for deterministic tests.
    """

    def __init__(
        self,
        person_track_id: str,
        config: LifecycleConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time as _time

        self.person_track_id = person_track_id
        self._cfg = config or LifecycleConfig()
        self._clock = clock or _time.monotonic

        now = self._clock()
        self.state = PersonLifecycleState.NEW_CANDIDATE
        self.confidence = 0.5
        self.first_seen = now
        self.last_seen = now
        self._hit_streak = 0
        self._miss_streak = 0
        self._lost_since: float | None = None
        self._active_until: float = 0.0
        self.last_transition: LifecycleTransition | None = None

    # ── External hooks (called by sibling packages, not by this FSM itself) ──

    def mark_active_interaction(self) -> None:
        """Called by gesture/speaker packages when this person addresses the robot."""
        self._active_until = self._clock() + self._cfg.active_interaction_hold_sec
        if self.state == PersonLifecycleState.PRESENT:
            self._transition(
                PersonLifecycleState.ACTIVE_INTERACTION, "external: interaction signal"
            )

    # ── Per-cycle update ─────────────────────────────────────────────────────

    def update(self, seen_this_cycle: bool, match_confidence: float = 1.0) -> LifecycleTransition:
        """Advance the FSM by one perception cycle.

        Args:
            seen_this_cycle: True if a detection was associated to this person
                this cycle (by face/spatial/raw-track-id matching upstream).
            match_confidence: confidence of that association, used to update
                ``self.confidence`` when seen.

        Returns:
            The :class:`LifecycleTransition` for this cycle (may be a no-op
            "stayed in <state>" transition — callers check ``from_state ==
            to_state`` to distinguish a real change from a steady-state tick).
        """
        now = self._clock()

        if self.state == PersonLifecycleState.LEFT_SCENE:
            # Terminal — no resurrection. The scene manager is responsible for
            # allocating a brand-new person_track_id (and RecallBuffer-linking
            # known_person_id) if this individual is detected again later.
            return self._transition(PersonLifecycleState.LEFT_SCENE, "terminal")

        if self.state == PersonLifecycleState.REAPPEARED:
            # One-shot: always collapses to PRESENT on the very next cycle,
            # regardless of seen_this_cycle (it was just re-matched this cycle).
            self.last_seen = now
            self.confidence = max(self.confidence, 0.6)
            return self._transition(
                PersonLifecycleState.PRESENT, "reappeared -> present (one-shot complete)"
            )

        if seen_this_cycle:
            self.last_seen = now
            self.confidence = max(self.confidence, min(1.0, match_confidence))
            self._miss_streak = 0
            self._lost_since = None

            if self.state == PersonLifecycleState.NEW_CANDIDATE:
                self._hit_streak += 1
                if self._hit_streak >= self._cfg.confirmation_hits:
                    return self._transition(PersonLifecycleState.PRESENT, "confirmed after N hits")
                return self._transition(
                    PersonLifecycleState.NEW_CANDIDATE, "candidate accumulating hits"
                )

            if self.state == PersonLifecycleState.ACTIVE_INTERACTION:
                if now < self._active_until:
                    return self._transition(
                        PersonLifecycleState.ACTIVE_INTERACTION, "interaction still active"
                    )
                return self._transition(PersonLifecycleState.PRESENT, "interaction hold expired")

            if self.state == PersonLifecycleState.TEMPORARILY_LOST:
                # This path is for a low-confidence "blip" recovery where the
                # scene manager re-associated by raw track_id continuity (i.e.
                # the upstream detector never actually lost this person — it
                # was a single noisy frame). A genuine re-match after a real
                # gap (face/spatial/body-reid match against a TEMPORARILY_LOST
                # record with a *different* raw track_id) must go through
                # mark_reappeared() instead, which the scene manager calls
                # explicitly rather than update(seen_this_cycle=True).
                return self._transition(
                    PersonLifecycleState.PRESENT, "blip recovery — no real loss occurred"
                )

            # PRESENT, seen again.
            return self._transition(PersonLifecycleState.PRESENT, "present, tracked")

        # ── Not seen this cycle ──────────────────────────────────────────────
        if self.state == PersonLifecycleState.NEW_CANDIDATE:
            self._hit_streak = 0
            self._miss_streak += 1
            if self._miss_streak > self._cfg.candidate_miss_limit:
                return self._transition(
                    PersonLifecycleState.LEFT_SCENE, "candidate never confirmed — discarding"
                )
            return self._transition(
                PersonLifecycleState.NEW_CANDIDATE, "candidate missed, not yet discarded"
            )

        if self.state in (PersonLifecycleState.PRESENT, PersonLifecycleState.ACTIVE_INTERACTION):
            self._lost_since = now
            self._miss_streak = 1
            return self._transition(
                PersonLifecycleState.TEMPORARILY_LOST, "missed this cycle — NOT assuming departure"
            )

        if self.state == PersonLifecycleState.TEMPORARILY_LOST:
            self._miss_streak += 1
            # NOTE: must compare to None, not use `self._lost_since or now` —
            # _lost_since can legitimately be exactly 0.0 (clock start), which
            # is falsy in Python and would silently collapse elapsed to 0.
            lost_since = self._lost_since if self._lost_since is not None else now
            elapsed = now - lost_since
            self.confidence = max(
                0.05, self.confidence - self._cfg.confidence_decay_per_sec * (1.0 / 30.0)
            )
            if elapsed >= self._cfg.loss_grace_sec:
                return self._transition(
                    PersonLifecycleState.LEFT_SCENE,
                    f"grace window ({self._cfg.loss_grace_sec}s) expired",
                )
            return self._transition(
                PersonLifecycleState.TEMPORARILY_LOST, "still within loss-grace window"
            )

        raise AssertionError(f"unreachable lifecycle state: {self.state}")  # pragma: no cover

    def mark_reappeared(self, match_confidence: float) -> LifecycleTransition:
        """Called by the scene manager when a TEMPORARILY_LOST person is re-matched
        (by face_id, spatial proximity, or body re-id) in the current cycle.
        """
        if self.state != PersonLifecycleState.TEMPORARILY_LOST:
            raise ValueError(
                f"mark_reappeared() only valid from TEMPORARILY_LOST, was {self.state}"
            )
        self.last_seen = self._clock()
        self.confidence = max(self.confidence, min(1.0, match_confidence))
        self._miss_streak = 0
        self._lost_since = None
        return self._transition(PersonLifecycleState.REAPPEARED, "re-matched after temporary loss")

    @property
    def time_since_last_seen_sec(self) -> float:
        return max(0.0, self._clock() - self.last_seen)

    def _transition(self, to_state: PersonLifecycleState, reason: str) -> LifecycleTransition:
        from_state = self.state
        self.state = to_state
        t = LifecycleTransition(
            person_track_id=self.person_track_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            timestamp=self._clock(),
        )
        self.last_transition = t
        return t
