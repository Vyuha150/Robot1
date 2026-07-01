"""Abstract dual-channel motor driver -- the interface every drive-base
motor controller in this repo implements (Cytron MDDS30 today, mirrors
CameraDriver/ServoDriver's abstract-base pattern exactly).

This is the fix for docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 1
(CRITICAL): before this driver existed, nothing in the repo could
translate an approved velocity command into a physical wheel motion --
Nav2 could plan and the safety gate could approve, but the base could not
move, on ANY topology (single-Pi or three-Pi).
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class WheelCommand:
    left_mps: float  # target left wheel linear speed, m/s (signed)
    right_mps: float  # target right wheel linear speed, m/s (signed)


@dataclass
class WheelReading:
    left_mps: float  # measured/estimated left wheel speed, m/s
    right_mps: float  # measured/estimated right wheel speed, m/s
    left_distance_m: float  # cumulative left wheel distance (encoder-derived or estimated)
    right_distance_m: float
    timestamp: float = field(default_factory=time.monotonic)


class MotorDriver(DriverBase):
    """Dual-channel drive motor controller.

    Subclasses implement `_do_connect` / `_do_disconnect` (DriverBase) plus
    `set_wheel_speeds` / `read_wheels`. No encoder feedback is assumed to
    exist at the driver level -- `read_wheels()` may return the last
    commanded speed integrated over time (open-loop estimate) if the
    physical motors have no encoders, and MUST say so honestly via
    `has_encoders`, never silently claim closed-loop odometry it can't
    provide.
    """

    def __init__(self, max_speed_mps: float = 1.0, has_encoders: bool = False, **kwargs) -> None:
        super().__init__("motor", **kwargs)
        self.max_speed_mps = max_speed_mps
        self.has_encoders = has_encoders

    @abstractmethod
    def set_wheel_speeds(self, command: WheelCommand) -> None:
        """Command left/right wheel speeds. Raises DriverFault on hardware error."""

    @abstractmethod
    def read_wheels(self) -> WheelReading:
        """Return the latest wheel speed/distance reading. Raises DriverFault
        if not connected."""

    @abstractmethod
    def emergency_stop(self) -> None:
        """Immediately zero both wheel speeds. Must never raise -- best-effort,
        called from safety-critical paths that cannot handle an exception."""
