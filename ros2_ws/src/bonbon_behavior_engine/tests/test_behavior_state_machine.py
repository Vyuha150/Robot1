"""Tests for bonbon_behavior_engine.core.behavior_state_machine."""

from __future__ import annotations

import pytest

from bonbon_behavior_engine.core.behavior_state_machine import (
    BehaviorState,
    BehaviorStateMachine,
)


class TestInitialState:
    def test_starts_in_idle(self):
        fsm = BehaviorStateMachine()
        assert fsm.current_state == BehaviorState.IDLE

    def test_initial_state_name_is_idle(self):
        fsm = BehaviorStateMachine()
        assert fsm.current_state_name == "IDLE"

    def test_history_has_one_entry_at_init(self):
        fsm = BehaviorStateMachine()
        assert len(fsm.history()) == 1


class TestLegalTransitions:
    def test_idle_to_greeting(self):
        fsm = BehaviorStateMachine()
        assert fsm.transition(BehaviorState.GREETING) is True
        assert fsm.current_state == BehaviorState.GREETING

    def test_idle_to_navigating(self):
        fsm = BehaviorStateMachine()
        assert fsm.transition(BehaviorState.NAVIGATING) is True

    def test_greeting_to_interacting(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.GREETING)
        assert fsm.transition(BehaviorState.INTERACTING) is True

    def test_interacting_to_navigating(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.INTERACTING)
        assert fsm.transition(BehaviorState.NAVIGATING) is True

    def test_navigating_to_idle(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.NAVIGATING)
        assert fsm.transition(BehaviorState.IDLE) is True

    def test_any_state_to_alerting(self):
        """ALERTING should be reachable from most states."""
        states_that_allow_alerting = [
            BehaviorState.IDLE,
            BehaviorState.GREETING,
            BehaviorState.INTERACTING,
            BehaviorState.NAVIGATING,
            BehaviorState.SERVING,
        ]
        for start in states_that_allow_alerting:
            fsm = BehaviorStateMachine()
            fsm.force_transition(start)
            result = fsm.transition(BehaviorState.ALERTING)
            assert result is True, f"Expected ALERTING from {start.name}"


class TestIllegalTransitions:
    def test_idle_to_interacting_is_illegal(self):
        """IDLE → INTERACTING skips GREETING; should be rejected."""
        fsm = BehaviorStateMachine()
        result = fsm.transition(BehaviorState.INTERACTING)
        assert result is False
        assert fsm.current_state == BehaviorState.IDLE

    def test_greeting_to_serving_is_illegal(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.GREETING)
        result = fsm.transition(BehaviorState.SERVING)
        assert result is False

    def test_alerting_to_greeting_is_illegal(self):
        fsm = BehaviorStateMachine()
        fsm.force_transition(BehaviorState.ALERTING)
        result = fsm.transition(BehaviorState.GREETING)
        assert result is False

    def test_same_state_is_no_op(self):
        fsm = BehaviorStateMachine()
        result = fsm.transition(BehaviorState.IDLE)
        assert result is True
        assert fsm.current_state == BehaviorState.IDLE


class TestForceTransition:
    def test_force_bypasses_legal_check(self):
        fsm = BehaviorStateMachine()
        # IDLE → INTERACTING is illegal under normal rules
        fsm.force_transition(BehaviorState.INTERACTING, "reset")
        assert fsm.current_state == BehaviorState.INTERACTING

    def test_history_records_forced_entry(self):
        fsm = BehaviorStateMachine()
        fsm.force_transition(BehaviorState.ALERTING, "emergency")
        last = fsm.history(1)[-1]
        assert "FORCED" in last.reason


class TestHistory:
    def test_history_grows_with_transitions(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.GREETING)
        fsm.transition(BehaviorState.INTERACTING)
        assert len(fsm.history()) == 3  # init + 2 transitions

    def test_reason_stored_in_history(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.GREETING, reason="person detected")
        last = fsm.history(1)[-1]
        assert "person detected" in last.reason

    def test_history_limit_respected(self):
        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.NAVIGATING)
        result = fsm.history(last_n=1)
        assert len(result) == 1


class TestListeners:
    def test_listener_called_on_transition(self):
        events = []
        fsm = BehaviorStateMachine()
        fsm.add_listener(lambda new, old, reason: events.append((new, old)))
        fsm.transition(BehaviorState.GREETING)
        assert len(events) == 1
        assert events[0][0] == BehaviorState.GREETING
        assert events[0][1] == BehaviorState.IDLE

    def test_listener_not_called_on_noop(self):
        events = []
        fsm = BehaviorStateMachine()
        fsm.add_listener(lambda *a: events.append(a))
        fsm.transition(BehaviorState.IDLE)  # same state
        assert len(events) == 0

    def test_failing_listener_does_not_break_fsm(self):
        fsm = BehaviorStateMachine()
        fsm.add_listener(lambda *a: (_ for _ in ()).throw(RuntimeError("test")))
        # Should not raise
        fsm.transition(BehaviorState.GREETING)
        assert fsm.current_state == BehaviorState.GREETING


class TestCanTransitionTo:
    def test_legal_transition_returns_true(self):
        fsm = BehaviorStateMachine()
        assert fsm.can_transition_to(BehaviorState.GREETING) is True

    def test_illegal_transition_returns_false(self):
        fsm = BehaviorStateMachine()
        assert fsm.can_transition_to(BehaviorState.INTERACTING) is False
