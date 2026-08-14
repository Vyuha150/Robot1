"""bonbon_hardware_telemetry.core.trigger -- the one shared, rclpy-free
output type every core/*_metrics.py module returns alongside its metrics
snapshot. hardware_telemetry_node.py is the only place a
TelemetryTrigger is turned into a real bonbon_msgs/HalFault and
published into the ALREADY-EXISTING bonbon_fault_manager ingestion
pipeline -- this module intentionally does not import bonbon_msgs so the
core/ package stays pure Python and unit-testable without a ROS2
environment, matching bonbon_gesture.logic.frame_gate and
bonbon_llm.safety.command_filter's precedent from this same workstream.

Severity mirrors bonbon_msgs/HalFault's own INFO/WARN/ERROR/FATAL uint8
constants exactly (0/1/2/3) -- keep these two definitions in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    INFO = 0
    WARN = 1
    ERROR = 2
    FATAL = 3


@dataclass(frozen=True)
class TelemetryTrigger:
    """device/code/message map directly onto HalFault's own fields;
    is_recovered lets a metrics module emit an explicit recovery event
    (e.g. a stepper clearing lost_sync) rather than the fault simply
    stopping being reported, which fault_manager's ingestion already
    treats as a distinct, real signal."""

    device: str
    severity: Severity
    code: str
    message: str
    is_recovered: bool = False
