"""Abstract closed-loop stepper driver — the interface every stepper
controller in this repo implements (NEMA17 closed-loop today), mirroring
MotorDriver/ServoDriver's abstract-base pattern exactly.

This is the fix for docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 2: the
"HEAD pan L/R" and "RIGHT ARM" (shoulder) joints in the BOM's "Hand
Gestures & Head Pan" sheet are 2x NEMA17 CLOSED-LOOP steppers, not
Dynamixel servos and not open-loop steppers -- closed-loop steppers are
the one actuator in the entire BOM that can report a real hardware fault
(stall / lost-sync), which is exactly the "see the issues on failure"
capability requested for this hardware.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class StepperReading:
    stepper_id: int
    position_rad: float  # tracked position (open-loop step count while healthy)
    velocity_rads: float
    is_stalled: bool  # debounced ALM (alarm) signal -- see StallFaultTracker
    lost_sync: bool  # true once a stall has been confirmed and not yet cleared
    enabled: bool
    error_code: int = 0
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class StepperCommand:
    stepper_id: int
    target_position_rad: float
    velocity_limit_rads: float = 1.0  # 0 = use driver default


class StepperDriver(DriverBase):
    def __init__(self, stepper_ids: list[int], **kwargs) -> None:
        super().__init__("stepper", **kwargs)
        self.stepper_ids = stepper_ids

    @abstractmethod
    def read_all(self) -> list[StepperReading]:
        """Return current state of all steppers. Raises DriverFault on error."""

    @abstractmethod
    def read_stepper(self, stepper_id: int) -> StepperReading:
        """Return state of one stepper."""

    @abstractmethod
    def write_command(self, cmd: StepperCommand) -> None:
        """Command one stepper toward a target position."""

    @abstractmethod
    def write_commands(self, cmds: list[StepperCommand]) -> None:
        """Command multiple steppers in one transaction."""

    @abstractmethod
    def enable_torque(self, stepper_id: int, enabled: bool) -> None:
        """Enable or disable holding torque on one stepper."""

    @abstractmethod
    def enable_all_torque(self, enabled: bool) -> None:
        """Enable or disable holding torque on all registered steppers."""

    @abstractmethod
    def clear_stall(self, stepper_id: int) -> None:
        """Acknowledge/clear a confirmed stall (lost_sync) after the
        alarm condition has physically cleared -- a stall is a latched
        fault, not an instantaneous one, matching how real closed-loop
        stepper drivers' ALM output behaves (see StallFaultTracker)."""
