"""Unit tests for PersonLifecycleFSM — the per-person identity lifecycle.

These verify the explicit project rule: a person is never declared gone from a
single missed frame, and every other lifecycle transition the brief specifies.
"""

from __future__ import annotations

import pytest
from bonbon_multi_person_tracker.core.lifecycle_state_machine import (
    LifecycleConfig,
    PersonLifecycleFSM,
    PersonLifecycleState,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _fsm(**cfg_overrides):
    clock = _Clock()
    cfg = LifecycleConfig(**cfg_overrides)
    return PersonLifecycleFSM("p1", config=cfg, clock=clock), clock


class TestNewCandidate:
    def test_starts_as_new_candidate(self):
        fsm, _ = _fsm()
        assert fsm.state == PersonLifecycleState.NEW_CANDIDATE

    def test_confirms_after_n_hits(self):
        fsm, _ = _fsm(confirmation_hits=2)
        fsm.update(seen_this_cycle=True)
        assert fsm.state == PersonLifecycleState.NEW_CANDIDATE
        t = fsm.update(seen_this_cycle=True)
        assert fsm.state == PersonLifecycleState.PRESENT
        assert t.from_state == PersonLifecycleState.NEW_CANDIDATE
        assert t.to_state == PersonLifecycleState.PRESENT

    def test_miss_resets_hit_streak(self):
        fsm, _ = _fsm(confirmation_hits=3)
        fsm.update(seen_this_cycle=True)
        fsm.update(seen_this_cycle=False)  # resets streak
        fsm.update(seen_this_cycle=True)
        fsm.update(seen_this_cycle=True)
        # Streak was reset, so 2 consecutive hits after the miss is not enough
        # for confirmation_hits=3.
        assert fsm.state == PersonLifecycleState.NEW_CANDIDATE

    def test_discarded_after_miss_limit_never_confirmed(self):
        fsm, _ = _fsm(candidate_miss_limit=2)
        fsm.update(seen_this_cycle=False)
        fsm.update(seen_this_cycle=False)
        t = fsm.update(seen_this_cycle=False)
        assert t.to_state == PersonLifecycleState.LEFT_SCENE
        assert "never confirmed" in t.reason


class TestNeverDeclareGoneFromOneFrame:
    """The explicit hard rule from the project brief."""

    def test_single_miss_from_present_is_temporarily_lost_not_left(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)  # -> PRESENT
        assert fsm.state == PersonLifecycleState.PRESENT
        t = fsm.update(seen_this_cycle=False)  # one missed frame
        assert t.to_state == PersonLifecycleState.TEMPORARILY_LOST
        assert t.to_state != PersonLifecycleState.LEFT_SCENE

    def test_left_scene_only_after_grace_window(self):
        fsm, clock = _fsm(confirmation_hits=1, loss_grace_sec=2.0)
        fsm.update(seen_this_cycle=True)  # PRESENT
        fsm.update(seen_this_cycle=False)  # TEMPORARILY_LOST, t=0
        clock.advance(1.0)
        t1 = fsm.update(seen_this_cycle=False)
        assert t1.to_state == PersonLifecycleState.TEMPORARILY_LOST  # still within grace
        clock.advance(1.5)  # total 2.5s > 2.0s grace
        t2 = fsm.update(seen_this_cycle=False)
        assert t2.to_state == PersonLifecycleState.LEFT_SCENE

    def test_confidence_decays_while_lost_but_never_hits_zero(self):
        fsm, clock = _fsm(confirmation_hits=1, loss_grace_sec=100.0)
        fsm.update(seen_this_cycle=True)
        fsm.update(seen_this_cycle=False)
        for _ in range(50):
            clock.advance(0.1)
            fsm.update(seen_this_cycle=False)
        assert fsm.confidence > 0.0
        assert fsm.confidence >= 0.05


class TestReappearance:
    def test_mark_reappeared_from_temporarily_lost(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)  # PRESENT
        fsm.update(seen_this_cycle=False)  # TEMPORARILY_LOST
        t = fsm.mark_reappeared(match_confidence=0.8)
        assert t.to_state == PersonLifecycleState.REAPPEARED
        assert fsm.confidence >= 0.8

    def test_reappeared_is_one_shot_then_present(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)
        fsm.update(seen_this_cycle=False)
        fsm.mark_reappeared(0.7)
        assert fsm.state == PersonLifecycleState.REAPPEARED
        t = fsm.update(seen_this_cycle=True)  # next cycle, regardless of input
        assert t.to_state == PersonLifecycleState.PRESENT

    def test_reappeared_rejected_from_wrong_state(self):
        fsm, _ = _fsm()
        with pytest.raises(ValueError):
            fsm.mark_reappeared(0.5)


class TestActiveInteraction:
    def test_mark_active_interaction_from_present(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)  # PRESENT
        fsm.mark_active_interaction()
        assert fsm.state == PersonLifecycleState.ACTIVE_INTERACTION

    def test_active_interaction_holds_then_decays_to_present(self):
        fsm, clock = _fsm(confirmation_hits=1, active_interaction_hold_sec=1.0)
        fsm.update(seen_this_cycle=True)
        fsm.mark_active_interaction()
        clock.advance(0.5)
        t1 = fsm.update(seen_this_cycle=True)
        assert t1.to_state == PersonLifecycleState.ACTIVE_INTERACTION
        clock.advance(1.0)  # past the hold window
        t2 = fsm.update(seen_this_cycle=True)
        assert t2.to_state == PersonLifecycleState.PRESENT

    def test_active_interaction_interrupted_by_miss_goes_temporarily_lost(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)
        fsm.mark_active_interaction()
        t = fsm.update(seen_this_cycle=False)
        assert t.to_state == PersonLifecycleState.TEMPORARILY_LOST


class TestSteadyState:
    def test_present_stays_present_when_seen(self):
        fsm, _ = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)
        t = fsm.update(seen_this_cycle=True)
        assert t.from_state == PersonLifecycleState.PRESENT
        assert t.to_state == PersonLifecycleState.PRESENT

    def test_left_scene_is_terminal(self):
        fsm, _ = _fsm(candidate_miss_limit=0)
        fsm.update(seen_this_cycle=False)  # immediately discarded
        assert fsm.state == PersonLifecycleState.LEFT_SCENE
        t = fsm.update(seen_this_cycle=True)  # no resurrection
        assert t.to_state == PersonLifecycleState.LEFT_SCENE

    def test_time_since_last_seen(self):
        fsm, clock = _fsm(confirmation_hits=1)
        fsm.update(seen_this_cycle=True)
        clock.advance(3.0)
        assert abs(fsm.time_since_last_seen_sec - 3.0) < 1e-6
