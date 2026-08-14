"""bonbon_distributed_network_monitor.core.trigger -- the rclpy-free
output type this package's node turns into a real bonbon_msgs/HalFault.
Deliberately a small self-contained copy of the same shape
bonbon_hardware_telemetry.core.trigger.TelemetryTrigger uses (which
itself mirrors HalFault's fields) rather than an exec_depend on that
unrelated package for a 20-line dataclass -- these two packages monitor
different domains (physical hardware vs network time-sync) and
shouldn't be coupled together just to share a struct shape.

Severity mirrors bonbon_msgs/HalFault's own INFO/WARN/ERROR/FATAL uint8
constants exactly (0/1/2/3).
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
    device: str
    severity: Severity
    code: str
    message: str
    is_recovered: bool = False
