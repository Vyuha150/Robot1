"""Abstract Dynamixel servo driver."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class ServoReading:
    servo_id: int
    position_rad: float  # current position
    velocity_rads: float  # current velocity
    load_percent: float  # motor load 0–100 %
    temperature_c: float
    voltage_v: float
    error_code: int = 0  # Dynamixel hardware error byte
    torque_enabled: bool = True
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class ServoCommand:
    servo_id: int
    target_position_rad: float
    velocity_limit_rads: float = 1.0  # 0 = use driver default
    torque_limit_percent: float = 100.0
    profile_acceleration: float = 0.0  # 0 = use driver default


class ServoDriver(DriverBase):
    def __init__(self, servo_ids: list[int], **kwargs) -> None:
        super().__init__("servo", **kwargs)
        self.servo_ids = servo_ids

    @abstractmethod
    def read_all(self) -> list[ServoReading]:
        """Return current state of all servos.  Raises DriverFault on error."""

    @abstractmethod
    def read_servo(self, servo_id: int) -> ServoReading:
        """Return state of one servo."""

    @abstractmethod
    def write_command(self, cmd: ServoCommand) -> None:
        """Send position/velocity command to one servo."""

    @abstractmethod
    def write_commands(self, cmds: list[ServoCommand]) -> None:
        """Sync-write to multiple servos in one transaction."""

    @abstractmethod
    def enable_torque(self, servo_id: int, enabled: bool) -> None:
        """Enable or disable torque on one servo."""

    @abstractmethod
    def enable_all_torque(self, enabled: bool) -> None:
        """Enable or disable torque on all registered servos."""
