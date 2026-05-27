"""Abstract battery / power-monitor driver."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase

# 3S LiPo voltage → percent lookup (11.1 V nominal)
_VOLTAGE_TABLE = [
    (12.6, 100),
    (12.3, 90),
    (12.0, 80),
    (11.8, 70),
    (11.6, 60),
    (11.4, 50),
    (11.2, 40),
    (11.0, 30),
    (10.8, 20),
    (10.5, 10),
    (10.2, 5),
    (9.9, 0),
]


def voltage_to_percent(v: float) -> float:
    """Linear interpolation from voltage to SoC percent."""
    if v >= _VOLTAGE_TABLE[0][0]:
        return 100.0
    if v <= _VOLTAGE_TABLE[-1][0]:
        return 0.0
    for i in range(len(_VOLTAGE_TABLE) - 1):
        v_hi, p_hi = _VOLTAGE_TABLE[i]
        v_lo, p_lo = _VOLTAGE_TABLE[i + 1]
        if v_lo <= v <= v_hi:
            t = (v - v_lo) / (v_hi - v_lo)
            return p_lo + t * (p_hi - p_lo)
    return 0.0


@dataclass
class BatteryReading:
    voltage_v: float
    current_a: float  # negative = discharging
    power_w: float
    percent: float  # 0–100
    temperature_c: float = 25.0
    time_remaining_sec: float = -1.0  # -1 = unknown
    is_charging: bool = False
    cell_voltages: list = field(default_factory=list)  # per-cell if BMS available
    timestamp: float = field(default_factory=time.monotonic)


class BatteryDriver(DriverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__("battery", **kwargs)

    @abstractmethod
    def read(self) -> BatteryReading:
        """Return latest battery reading.  Raises DriverFault on error."""
