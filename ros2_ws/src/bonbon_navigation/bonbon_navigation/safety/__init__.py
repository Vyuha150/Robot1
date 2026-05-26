"""bonbon_navigation.safety — Velocity safety gating."""
from bonbon_navigation.safety.safety_stop_bridge import (
    GatedVelocity,
    SafetyStopBridge,
    SAFETY_INITIALIZING,
    SAFETY_NORMAL,
    SAFETY_CAUTION,
    SAFETY_DANGER,
    SAFETY_DOCKING,
    SAFETY_DEGRADED,
    SAFETY_FAULT,
    SAFETY_SAFE_STOP,
)

__all__ = [
    "GatedVelocity",
    "SafetyStopBridge",
    "SAFETY_INITIALIZING",
    "SAFETY_NORMAL",
    "SAFETY_CAUTION",
    "SAFETY_DANGER",
    "SAFETY_DOCKING",
    "SAFETY_DEGRADED",
    "SAFETY_FAULT",
    "SAFETY_SAFE_STOP",
]
