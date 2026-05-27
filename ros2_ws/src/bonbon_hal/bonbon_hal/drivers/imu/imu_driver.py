"""Abstract IMU driver — MPU-6050 9-DOF."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class ImuReading:
    # Linear acceleration m/s²  (body frame: x=forward, y=left, z=up)
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 9.81  # resting = +g upward

    # Angular velocity rad/s
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0

    # Orientation quaternion (x,y,z,w) — (0,0,0,1) when not available
    orient_x: float = 0.0
    orient_y: float = 0.0
    orient_z: float = 0.0
    orient_w: float = 1.0
    orientation_valid: bool = False  # only True when a filter is running

    # Onboard temperature sensor
    temperature_c: float = 25.0

    # Covariance — -1 = unknown
    accel_covariance: float = -1.0
    gyro_covariance: float = -1.0
    orient_covariance: float = -1.0

    timestamp: float = field(default_factory=time.monotonic)


class ImuDriver(DriverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__("imu", **kwargs)

    @abstractmethod
    def read(self) -> ImuReading:
        """Return latest raw IMU reading.  Raises DriverFault on error."""

    @abstractmethod
    def calibrate(self) -> None:
        """
        Run zero-offset calibration (robot must be stationary and level).
        Blocks until complete.
        """
