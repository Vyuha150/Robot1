"""Abstract LIDAR driver — RPLIDAR S2."""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class LidarScan:
    ranges: list[float]  # metres; inf = no return
    intensities: list[float]  # 0–255 per ray
    angle_min_rad: float = -math.pi
    angle_max_rad: float = math.pi
    angle_increment_rad: float = field(init=False)
    time_increment_sec: float = 0.0
    scan_time_sec: float = 0.1
    range_min_m: float = 0.15
    range_max_m: float = 30.0
    timestamp: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        n = len(self.ranges)
        self.angle_increment_rad = (self.angle_max_rad - self.angle_min_rad) / max(n - 1, 1)


class LidarDriver(DriverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__("lidar", **kwargs)

    @abstractmethod
    def read_scan(self) -> LidarScan:
        """Return one complete 360° scan.  Raises DriverFault on error."""
