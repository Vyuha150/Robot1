"""BehaviorStateMachine — finite-state machine for BonBon's behavior modes.

States
------
IDLE         — robot is idle, ambient behaviour only
GREETING     — actively greeting a newly detected person
INTERACTING  — in conversation or task interaction with a person
NAVIGATING   — moving to a goal (under navigation stack control)
SERVING      — performing a specific service task (delivery, guidance)
ALERTING     — handling an emergency or operator alert
RETURNING    — returning to home/dock position

The FSM enforces legal transitions.  Illegal transitions are logged and rejected.

Note: The FSM tracks **robot behavioural intent**, not physical state.  Physical
safety state is managed exclusively by bonbon_safety.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, FrozenSet, List, Optional, Set

_logger = logging.getLogger(__name__)


class BehaviorState(IntEnum):
    IDLE        = 0
    GREETING    = 1
    INTERACTING = 2
    NAVIGATING  = 3
    SERVING     = 4
    ALERTING    = 5
    RETURNING   = 6


# Legal transitions: from → {allowed targets}
_TRANSITIONS: Dict[BehaviorState, FrozenSet[BehaviorState]] = {
    BehaviorState.IDLE:        frozenset({
        BehaviorState.GREETING,
        BehaviorState.NAVIGATING,
        BehaviorState.SERVING,
        BehaviorState.ALERTING,
        BehaviorState.RETURNING,
    }),
    BehaviorState.GREETING:    frozenset({
        BehaviorState.IDLE,
        BehaviorState.INTERACTING,
        BehaviorState.ALERTING,
    }),
    BehaviorState.INTERACTING: frozenset({
        BehaviorState.IDLE,
        BehaviorState.NAVIGATING,
        BehaviorState.SERVING,
        BehaviorState.ALERTING,
    }),
    BehaviorState.NAVIGATING:  frozenset({
        BehaviorState.IDLE,
        BehaviorState.INTERACTING,
        BehaviorState.SERVING,
        BehaviorState.ALERTING,
        BehaviorState.RETURNING,
    }),
    BehaviorState.SERVING:     frozenset({
        BehaviorState.IDLE,
        BehaviorState.INTERACTING,
        BehaviorState.NAVIGATING,
        BehaviorState.ALERTING,
        BehaviorState.RETURNING,
    }),
    BehaviorState.ALERTING:    frozenset({
        BehaviorState.IDLE,
        BehaviorState.RETURNING,
    }),
    BehaviorState.RETURNING:   frozenset({
        BehaviorState.IDLE,
        BehaviorState.ALERTING,
    }),
}


@dataclass
class StateEntry:
    """A single record in the state history."""

    state: BehaviorState
    entered_at: float = field(default_factory=time.monotonic)
    reason: str = ""


class BehaviorStateMachine:
    """Manages BonBon's behaviour state with legal-transition enforcement.

    Usage::

        fsm = BehaviorStateMachine()
        fsm.transition(BehaviorState.GREETING, reason="person detected")
        # fsm.current_state → BehaviorState.GREETING
    """

    def __init__(self) -> None:
        self._state: BehaviorState = BehaviorState.IDLE
        self._history: List[StateEntry] = [StateEntry(BehaviorState.IDLE, reason="init")]
        self._listeners: List = []   # callbacks(new_state, old_state, reason)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def transition(self, target: BehaviorState, reason: str = "") -> bool:
        """Attempt a transition to *target*.

        Args:
            target: The desired next state.
            reason: Human-readable justification (logged and stored).

        Returns:
            ``True`` on success, ``False`` if the transition is illegal.
        """
        if target == self._state:
            return True  # no-op

        allowed = _TRANSITIONS.get(self._state, frozenset())
        if target not in allowed:
            _logger.warning(
                "Illegal state transition: %s → %s (reason: %s)",
                self._state.name, target.name, reason,
            )
            return False

        old = self._state
        self._state = target
        entry = StateEntry(state=target, reason=reason)
        self._history.append(entry)

        _logger.info(
            "Behavior state: %s → %s (%s)",
            old.name, target.name, reason or "—",
        )

        for cb in self._listeners:
            try:
                cb(target, old, reason)
            except Exception as exc:  # noqa: BLE001
                _logger.error("State listener raised: %s", exc)

        return True

    def force_transition(self, target: BehaviorState, reason: str = "") -> None:
        """Bypass the legal-transition check.  Use only for emergency/reset."""
        old = self._state
        self._state = target
        self._history.append(StateEntry(state=target, reason=f"[FORCED] {reason}"))
        _logger.warning(
            "Forced behavior state: %s → %s (%s)",
            old.name, target.name, reason,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def current_state(self) -> BehaviorState:
        """The current behaviour state."""
        return self._state

    @property
    def current_state_name(self) -> str:
        return self._state.name

    def can_transition_to(self, target: BehaviorState) -> bool:
        """Return True if the transition *current → target* is legal."""
        return target in _TRANSITIONS.get(self._state, frozenset())

    def time_in_current_state(self) -> float:
        """Seconds elapsed since the last state entry."""
        return time.monotonic() - self._history[-1].entered_at

    def history(self, last_n: int = 10) -> List[StateEntry]:
        """Return the last *n* state entries."""
        return self._history[-last_n:]

    def add_listener(self, callback) -> None:
        """Register a callback ``fn(new_state, old_state, reason)``."""
        self._listeners.append(callback)
