"""ActuationSafetyGate — enforces safety-level gating on gesture execution.

The gate maintains the current safety level (updated from /bonbon/safety/state)
and evaluates whether a requested gesture at a given priority is permitted.

Safety level ↔ minimum permitted gesture priority::

    INITIALIZING (0) : 999  — no actuation during startup
    NORMAL       (1) :   0  — all gestures allowed
    CAUTION      (2) :   5  — normal+ priority
    DANGER       (3) :  10  — high priority only
    DOCKING      (4) :   5  — normal+ (docking manoeuvres need arm clearance)
    DEGRADED     (5) :  10  — high priority only
    FAULT        (6) :  20  — emergency only
    SAFE_STOP    (7) :  20  — emergency only

Priority convention (matches ActuationGesture.priority field):
    0 = low | 5 = normal | 10 = high | 20 = emergency
"""

from __future__ import annotations

import logging
from typing import Tuple

_logger = logging.getLogger(__name__)

# Safety level constants (mirrors bonbon_msgs/SafetyState.level).
LEVEL_INITIALIZING: int = 0
LEVEL_NORMAL:       int = 1
LEVEL_CAUTION:      int = 2
LEVEL_DANGER:       int = 3
LEVEL_DOCKING:      int = 4
LEVEL_DEGRADED:     int = 5
LEVEL_FAULT:        int = 6
LEVEL_SAFE_STOP:    int = 7

# Minimum gesture priority required at each safety level.
_MIN_PRIORITY: dict = {
    LEVEL_INITIALIZING: 999,
    LEVEL_NORMAL:         0,
    LEVEL_CAUTION:        5,
    LEVEL_DANGER:        10,
    LEVEL_DOCKING:        5,
    LEVEL_DEGRADED:      10,
    LEVEL_FAULT:         20,
    LEVEL_SAFE_STOP:     20,
}


class ActuationSafetyGate:
    """Stateful gate that allows or denies gesture execution.

    State is updated from the ROS2 SafetyState topic and must be refreshed
    before every evaluation.

    Thread safety: ``update_safety_state`` and ``is_allowed`` may be called
    from different threads; callers should hold an external lock when necessary.
    """

    def __init__(self) -> None:
        """Initialise in the most restrictive state (INITIALIZING, disabled)."""
        self._safety_level: int = LEVEL_INITIALIZING
        self._actuation_enabled: bool = False
        self._level_name: str = "INITIALIZING"

    # ------------------------------------------------------------------
    # State update (called from SafetyState subscriber callback)
    # ------------------------------------------------------------------

    def update_safety_state(
        self,
        level: int,
        actuation_enabled: bool,
        level_name: str = "",
    ) -> None:
        """Refresh the gate with the latest safety supervisor state.

        Args:
            level: Integer safety level (0–7).
            actuation_enabled: Whether the supervisor has enabled actuation.
            level_name: Human-readable level name for logging.
        """
        prev = self._safety_level
        self._safety_level = level
        self._actuation_enabled = actuation_enabled
        self._level_name = level_name or str(level)

        if level != prev:
            _logger.info(
                "ActuationSafetyGate: level %s → %s, actuation_enabled=%s",
                prev,
                self._level_name,
                actuation_enabled,
            )

    # ------------------------------------------------------------------
    # Gate evaluation
    # ------------------------------------------------------------------

    def is_allowed(
        self, gesture_name: str, priority: int
    ) -> Tuple[bool, str]:
        """Determine whether a gesture may execute at the current safety level.

        Args:
            gesture_name: Name of the requested gesture (used for logging only).
            priority: Requested priority (0=low … 20=emergency).

        Returns:
            A ``(allowed, reason)`` tuple.  ``allowed`` is ``True`` when the
            gesture may proceed.  ``reason`` is an empty string on approval or
            a human-readable explanation on denial.
        """
        if not self._actuation_enabled:
            reason = (
                f"Actuation disabled by safety supervisor "
                f"(level={self._level_name})."
            )
            _logger.debug(
                "Gesture '%s' DENIED: %s", gesture_name, reason
            )
            return False, reason

        min_prio = _MIN_PRIORITY.get(self._safety_level, 999)

        if priority < min_prio:
            reason = (
                f"Priority {priority} is insufficient for safety level "
                f"{self._level_name} (minimum required: {min_prio})."
            )
            _logger.debug(
                "Gesture '%s' DENIED: %s", gesture_name, reason
            )
            return False, reason

        _logger.debug(
            "Gesture '%s' APPROVED (priority=%d, level=%s).",
            gesture_name, priority, self._level_name,
        )
        return True, ""

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def safety_level(self) -> int:
        """Current integer safety level."""
        return self._safety_level

    @property
    def actuation_enabled(self) -> bool:
        """Whether actuation is currently enabled by the safety supervisor."""
        return self._actuation_enabled
