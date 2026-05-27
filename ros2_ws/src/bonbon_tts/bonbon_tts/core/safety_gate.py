"""
bonbon_tts.core.safety_gate
=============================
TTSSafetyGate — enforces the rule:

  The robot must NEVER continue speaking during emergency stop,
  safety halt, or critical actuation failure unless the speech is
  an EMERGENCY priority announcement.

This gate is driven by the ``/bonbon/safety/state`` ROS2 topic.
All priority decisions are made here; the ``SpeechSynthesizer``
calls :meth:`is_speech_allowed` before every synthesis attempt.

State machine
-------------
::

    NORMAL ──► DEGRADED ──► SAFETY_STOP ──► EMERGENCY_STOP
      ▲                          │                │
      └──────────────────────────┘                │
                                                  │
      NORMAL ◄── DEGRADED ◄──────────────────────┘

Transitions to ``SAFETY_STOP`` or ``EMERGENCY_STOP`` trigger an
immediate stop of current playback.  Transitioning back to NORMAL
or DEGRADED lifts the gate.
"""

from __future__ import annotations

import logging
import threading
from enum import StrEnum

from bonbon_tts.core.utterance_queue import Priority

logger = logging.getLogger(__name__)


class SafetyState(StrEnum):
    """Safety supervisor state values."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    SAFETY_STOP = "safety_stop"
    EMERGENCY_STOP = "emergency_stop"

    @classmethod
    def from_string(cls, s: str) -> SafetyState:
        """Parse case-insensitively; falls back to NORMAL."""
        try:
            return cls(s.lower())
        except ValueError:
            logger.warning("TTSSafetyGate: unknown safety state %r — treating as NORMAL", s)
            return cls.NORMAL


_HALT_STATES = frozenset({SafetyState.SAFETY_STOP, SafetyState.EMERGENCY_STOP})


class TTSSafetyGate:
    """
    Thread-safe safety gate for TTS speech output.

    Attributes
    ----------
    current_state:
        Most recent safety state received.
    is_halted:
        True when the system is in a halt state (speech blocked).

    Example
    -------
    ::

        gate = TTSSafetyGate()
        gate.update_state(SafetyState.SAFETY_STOP)
        gate.is_speech_allowed(Priority.NORMAL)    # → False
        gate.is_speech_allowed(Priority.EMERGENCY) # → True
    """

    def __init__(self) -> None:
        self._state = SafetyState.NORMAL
        self._lock = threading.Lock()

    # ── State updates ─────────────────────────────────────────────────────────

    def update_state(self, state: SafetyState) -> bool:
        """
        Update the safety state.

        Returns
        -------
        bool
            True if the system just *entered* a halt state (i.e. caller
            should stop current speech immediately).
        """
        with self._lock:
            prev = self._state
            self._state = state
            just_halted = (prev not in _HALT_STATES) and (state in _HALT_STATES)

        if just_halted:
            logger.warning("TTSSafetyGate: HALT entered — state=%s", state.value)
        elif prev in _HALT_STATES and state not in _HALT_STATES:
            logger.info("TTSSafetyGate: HALT lifted — state=%s", state.value)

        return just_halted

    # ── Policy queries ─────────────────────────────────────────────────────────

    def is_speech_allowed(self, priority: Priority) -> bool:
        """
        Return True if an utterance with *priority* may be synthesised
        and played in the current safety state.

        Rule:
          - NORMAL / DEGRADED → all priorities allowed
          - SAFETY_STOP / EMERGENCY_STOP → only ``EMERGENCY`` (0) allowed
        """
        with self._lock:
            state = self._state
        if state in _HALT_STATES:
            return priority == Priority.EMERGENCY
        return True

    def should_halt_speech(self) -> bool:
        """True if current playback must be stopped immediately."""
        with self._lock:
            return self._state in _HALT_STATES

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_state(self) -> SafetyState:
        with self._lock:
            return self._state

    @property
    def is_halted(self) -> bool:
        return self.should_halt_speech()
