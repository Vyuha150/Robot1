"""bonbon_fault_manager.core.fault_taxonomy
=============================================
The six-level fault taxonomy used across the whole fault registry.

This is deliberately richer than bonbon_msgs/HalFault's 4-level
severity (INFO/WARN/ERROR/FATAL) or bonbon_hal's 6-state DriverStatus:
those describe a single driver's own connectivity, not "how bad is this
for the robot as a whole and does a human need to act." FaultLevel adds
that judgment, mirrors bonbon_msgs/ComponentFault.msg's constants
exactly, and is the value component_rules.classify() and FaultRegistry
operate on.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Iterable


class FaultLevel(IntEnum):
    """Mirrors bonbon_msgs/msg/ComponentFault.msg's uint8 constants."""

    OK = 0
    WARNING = 1
    DEGRADED = 2
    FAULT = 3
    CRITICAL = 4
    BLOCKED = 5


def worst(levels: Iterable[FaultLevel]) -> FaultLevel:
    """Roll up a collection of levels to the single worst one.

    Empty input means no components are known yet -- OK, not an error.
    """
    result = FaultLevel.OK
    for level in levels:
        if level > result:
            result = level
    return result


def is_actionable(level: FaultLevel) -> bool:
    """True if a human/operator should be alerted, not just logged.

    WARNING and above surface on the dashboard; OK never does.
    """
    return level >= FaultLevel.WARNING
