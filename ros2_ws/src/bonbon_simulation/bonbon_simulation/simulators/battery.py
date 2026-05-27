from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BatteryState:
    percentage: float = 100.0
    voltage_v: float = 25.2
    is_charging: bool = False


class BatterySimulator:
    def __init__(self, initial_pct: float = 100.0, drain_pct_per_hour: float = 8.0) -> None:
        self.state = BatteryState(percentage=float(initial_pct))
        self.drain_pct_per_hour = float(drain_pct_per_hour)

    def step(self, dt_sec: float, moving: bool = True) -> None:
        if self.state.is_charging:
            self.state.percentage = min(100.0, self.state.percentage + dt_sec * 12.0 / 3600.0)
        else:
            multiplier = 1.0 if moving else 0.35
            self.state.percentage = max(0.0, self.state.percentage - dt_sec * self.drain_pct_per_hour * multiplier / 3600.0)
        self.state.voltage_v = 18.0 + (self.state.percentage / 100.0) * 7.2

    def set_low(self, pct: float = 9.0) -> None:
        self.state.percentage = float(pct)

    def dock(self) -> None:
        self.state.is_charging = True
