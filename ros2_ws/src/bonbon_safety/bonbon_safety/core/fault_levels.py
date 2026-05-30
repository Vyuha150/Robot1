"""Fallback-level model for system-wide fault handling.

Defines the six escalation levels every module uses to describe its response to
a fault, and maps them onto the existing 8-state :class:`SafetyLevel` so the
safety supervisor and per-module fault handlers share one vocabulary.

Fallback levels
---------------
L0 NORMAL          — normal operation, no degradation.
L1 DEGRADED        — a non-critical capability lost; keep operating reduced.
L2 SAFE_PAUSE      — pause motion/tasks, hold position, keep sensing.
L3 SAFE_STOP       — controlled stop; motion disabled, recovery may resume.
L4 EMERGENCY_STOP  — immediate hard stop / power cut; manual reset required.
L5 HUMAN_REQUIRED  — robot cannot self-recover; a human operator must act.

The mapping to SafetyLevel is deliberately conservative: a module reporting a
higher fallback level can only *raise* the supervisor's state, never lower it.
"""

from __future__ import annotations

from enum import IntEnum

from bonbon_safety.core.safety_state_machine import SafetyLevel


class FallbackLevel(IntEnum):
    """Six-level escalation ladder (monotonic — higher = more severe)."""

    NORMAL = 0
    DEGRADED = 1
    SAFE_PAUSE = 2
    SAFE_STOP = 3
    EMERGENCY_STOP = 4
    HUMAN_REQUIRED = 5


# Human-readable labels (stable strings for logs / diagnostics / dashboard).
FALLBACK_LABEL = {
    FallbackLevel.NORMAL: "normal",
    FallbackLevel.DEGRADED: "degraded",
    FallbackLevel.SAFE_PAUSE: "safe_pause",
    FallbackLevel.SAFE_STOP: "safe_stop",
    FallbackLevel.EMERGENCY_STOP: "emergency_stop",
    FallbackLevel.HUMAN_REQUIRED: "human_intervention_required",
}

# Fallback level → the SafetyLevel the supervisor should be at *least* in.
_FALLBACK_TO_SAFETY = {
    FallbackLevel.NORMAL: SafetyLevel.NORMAL,
    FallbackLevel.DEGRADED: SafetyLevel.DEGRADED,
    FallbackLevel.SAFE_PAUSE: SafetyLevel.CAUTION,
    FallbackLevel.SAFE_STOP: SafetyLevel.DANGER,
    FallbackLevel.EMERGENCY_STOP: SafetyLevel.SAFE_STOP,
    FallbackLevel.HUMAN_REQUIRED: SafetyLevel.FAULT,
}


def fallback_to_safety_level(level: FallbackLevel) -> SafetyLevel:
    """Map a fallback level to the minimum corresponding SafetyLevel."""
    return _FALLBACK_TO_SAFETY[FallbackLevel(level)]


def requires_operator(level: FallbackLevel) -> bool:
    """Return True when this fallback level demands an operator alert.

    SAFE_STOP and above always alert a human operator.
    """
    return FallbackLevel(level) >= FallbackLevel.SAFE_STOP


def is_self_recoverable(level: FallbackLevel) -> bool:
    """Return True when the robot may attempt automatic recovery.

    EMERGENCY_STOP and HUMAN_REQUIRED need a manual reset / human action.
    """
    return FallbackLevel(level) <= FallbackLevel.SAFE_STOP


def escalate(a: FallbackLevel, b: FallbackLevel) -> FallbackLevel:
    """Return the more severe of two fallback levels (monotonic max)."""
    return FallbackLevel(max(int(a), int(b)))
