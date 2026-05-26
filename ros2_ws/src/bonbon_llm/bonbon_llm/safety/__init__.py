"""
bonbon_llm.safety
=================
Three-layer safety stack:

  1. SafetyCommandFilter  — hard regex blocks + RISKY escalation
  2. CommandAuthorizer    — gates against live SafetyState snapshot
  3. HallucinationGuard   — grounding checks on LLM output

No LLM-generated text ever reaches actuators or the nav stack directly.
"""
from bonbon_llm.safety.command_filter import (
    FilterStatus,
    FilterResult,
    SafetyCommandFilter,
)
from bonbon_llm.safety.authorization import (
    AuthStatus,
    AuthorizationResult,
    SafetySnapshot,
    CommandAuthorizer,
    # Safety state constants
    SAFETY_INITIALIZING,
    SAFETY_NORMAL,
    SAFETY_CAUTION,
    SAFETY_DANGER,
    SAFETY_DOCKING,
    SAFETY_DEGRADED,
    SAFETY_FAULT,
    SAFETY_SAFE_STOP,
)
from bonbon_llm.safety.hallucination_guard import GuardResult, HallucinationGuard

__all__ = [
    # Command filter
    "FilterStatus",
    "FilterResult",
    "SafetyCommandFilter",
    # Authorization
    "AuthStatus",
    "AuthorizationResult",
    "SafetySnapshot",
    "CommandAuthorizer",
    "SAFETY_INITIALIZING",
    "SAFETY_NORMAL",
    "SAFETY_CAUTION",
    "SAFETY_DANGER",
    "SAFETY_DOCKING",
    "SAFETY_DEGRADED",
    "SAFETY_FAULT",
    "SAFETY_SAFE_STOP",
    # Hallucination guard
    "GuardResult",
    "HallucinationGuard",
]
