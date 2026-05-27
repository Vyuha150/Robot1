"""
test_battery_driver.py
======================
Tests for MockBatteryDriver: drain, charge, faults, voltage spike, sudden drop.
"""

from __future__ import annotations

import time

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.battery import BatteryReading, MockBatteryDriver
from bonbon_hal.drivers.battery.battery_driver import voltage_to_percent


class TestVoltageLookup:
    def test_full_voltage(self):
        assert voltage_to_percent(12.6) == pytest.approx(100.0)

    def test_empty_voltage(self):
        assert voltage_to_percent(9.9) == pytest.approx(0.0)

    def test_half_voltage_approx(self):
        pct = voltage_to_percent(11.4)
        assert 40 < pct < 60

    def test_below_empty_clamps_to_zero(self):
        assert voltage_to_percent(5.0) == 0.0

    def test_above_full_clamps_to_100(self):
        assert voltage_to_percent(15.0) == 100.0


@pytest.fixture
def drv() -> MockBatteryDriver:
    d = MockBatteryDriver(initial_percent=80.0)
    d.connect()
    return d


class TestMockBatteryNormal:
    def test_connect_ok(self, drv):
        assert drv.is_connected

    def test_read_returns_reading(self, drv):
        r = drv.read()
        assert isinstance(r, BatteryReading)

    def test_initial_percent_respected(self, drv):
        r = drv.read()
        assert 75.0 < r.percent < 85.0  # tolerance for drain + noise

    def test_voltage_consistent_with_percent(self, drv):
        r = drv.read()
        v_expected = 9.9 + r.percent / 100.0 * (12.6 - 9.9)
        assert abs(r.voltage_v - v_expected) < 0.5  # noise tolerance

    def test_current_negative_when_discharging(self, drv):
        r = drv.read()
        assert r.current_a < 0

    def test_battery_drains_over_reads(self):
        drv = MockBatteryDriver(initial_percent=50.0, drain_rate_pct_s=1.0)
        drv.connect()
        r1 = drv.read()
        time.sleep(0.1)  # wait a bit
        r2 = drv.read()
        assert r2.percent < r1.percent

    def test_charging_increases_percent(self):
        drv = MockBatteryDriver(initial_percent=50.0, is_charging=True, charge_rate_pct_s=1.0)
        drv.connect()
        r1 = drv.read()
        time.sleep(0.1)
        r2 = drv.read()
        assert r2.percent > r1.percent

    def test_is_charging_flag(self):
        drv = MockBatteryDriver(is_charging=True)
        drv.connect()
        r = drv.read()
        assert r.is_charging is True


class TestMockBatteryFaults:
    def test_read_without_connect_raises(self):
        drv = MockBatteryDriver()
        with pytest.raises(DriverFault) as exc:
            drv.read()
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_start_disconnected(self):
        drv = MockBatteryDriver(start_disconnected=True)
        ok = drv.connect()
        assert ok is False

    def test_i2c_disconnect_after_n(self):
        drv = MockBatteryDriver(disconnect_after_n=3)
        drv.connect()
        for _ in range(3):
            drv.read()
        with pytest.raises(DriverFault) as exc:
            drv.read()
        assert exc.value.error_code == "I2C_DISCONNECT"

    def test_voltage_spike(self):
        drv = MockBatteryDriver(voltage_spike_v=2.0)
        drv.connect()
        r = drv.read()
        # Spike on first read
        normal_v = 9.9 + (80.0 / 100.0) * (12.6 - 9.9)
        assert r.voltage_v > normal_v + 1.0
        # Next read: spike consumed
        r2 = drv.read()
        assert abs(r2.voltage_v - normal_v) < 0.5

    def test_sudden_drop(self):
        drv = MockBatteryDriver(initial_percent=80.0, sudden_drop_pct=40.0)
        drv.connect()
        r = drv.read()
        # After drop: should be ≈ 40%
        assert r.percent < 50.0


class TestMockBatteryRecovery:
    def test_reconnect_after_i2c_disconnect(self):
        drv = MockBatteryDriver(disconnect_after_n=2)
        drv.connect()
        drv.read()
        drv.read()
        try:
            drv.read()
        except DriverFault:
            pass
        drv.inject_fault(disc_after=0)
        ok = drv.reconnect()
        assert ok
        r = drv.read()
        assert isinstance(r, BatteryReading)
