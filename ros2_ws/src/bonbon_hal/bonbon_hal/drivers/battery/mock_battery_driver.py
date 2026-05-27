"""
Mock battery driver — simulates a 3S 40Ah LiPo discharging at
configurable rate, with optional charging simulation.

Fault injection:
  voltage_spike_v       : inject one-cycle voltage spike
  disconnect_after_n    : simulate I2C disconnect
  sudden_drop_pct       : suddenly drop SoC by this much (one cycle)
"""

from __future__ import annotations

import random
import time

from bonbon_hal.base.driver_base import DriverFault

from .battery_driver import BatteryDriver, BatteryReading


class MockBatteryDriver(BatteryDriver):

    # 3S LiPo: full=12.6V, nominal=11.1V, empty=9.9V
    FULL_V = 12.6
    EMPTY_V = 9.9

    def __init__(
        self,
        initial_percent: float = 85.0,
        drain_rate_pct_s: float = 0.001,  # 0.001% / read ≈ 100% in ~28 hrs at 10 Hz
        charge_rate_pct_s: float = 0.002,
        is_charging: bool = False,
        disconnect_after_n: int = 0,
        voltage_spike_v: float = 0.0,
        sudden_drop_pct: float = 0.0,
        start_disconnected: bool = False,
        noise_v: float = 0.02,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._pct = initial_percent
        self._drain_rate = drain_rate_pct_s
        self._charge_rate = charge_rate_pct_s
        self._charging = is_charging
        self._disc_after = disconnect_after_n
        self._spike_v = voltage_spike_v
        self._drop_pct = sudden_drop_pct
        self._noise_v = noise_v
        self._start_disc = start_disconnected
        self._read_count = 0
        self._last_read_t = time.monotonic()

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.02)
        return True

    def _do_disconnect(self) -> None:
        pass

    def read(self) -> BatteryReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")

        now = time.monotonic()
        dt = now - self._last_read_t
        self._last_read_t = now
        self._read_count += 1

        if self._disc_after > 0 and self._read_count > self._disc_after:
            self._record_fault("I2C_DISCONNECT", "Simulated I2C disconnect")
            raise DriverFault("I2C disconnect", "I2C_DISCONNECT")

        # Apply drain/charge
        if self._charging:
            self._pct = min(100.0, self._pct + self._charge_rate * dt * 100)
        else:
            self._pct = max(0.0, self._pct - self._drain_rate * dt * 100)

        # One-shot sudden drop
        if self._drop_pct > 0:
            self._pct = max(0.0, self._pct - self._drop_pct)
            self._drop_pct = 0.0

        # Voltage from percent (inverse of lookup)
        v_range = self.FULL_V - self.EMPTY_V
        voltage = self.EMPTY_V + (self._pct / 100.0) * v_range
        voltage += random.gauss(0, self._noise_v)

        if self._spike_v != 0.0:
            voltage += self._spike_v
            self._spike_v = 0.0

        current = random.gauss(-3.5 if not self._charging else 2.0, 0.1)
        power = voltage * current
        temp = random.gauss(35.0, 1.0)
        time_rem = (self._pct / 100.0) * 144000 if not self._charging else -1.0

        self._record_success()
        return BatteryReading(
            voltage_v=voltage,
            current_a=current,
            power_w=power,
            percent=self._pct,
            temperature_c=temp,
            time_remaining_sec=time_rem,
            is_charging=self._charging,
        )

    def set_charging(self, charging: bool) -> None:
        self._charging = charging

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
