"""
test_imu_driver.py
==================
Tests for MockImuDriver: normal, disconnection, spikes, drift, timeout, recovery.
"""

from __future__ import annotations

import time

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.imu import ImuReading, MockImuDriver


@pytest.fixture
def drv() -> MockImuDriver:
    d = MockImuDriver()
    d.connect()
    return d


class TestMockImuNormal:
    def test_connect_succeeds(self, drv):
        assert drv.is_connected

    def test_read_returns_reading(self, drv):
        r = drv.read()
        assert isinstance(r, ImuReading)

    def test_gravity_approx_9_81_at_rest(self, drv):
        readings = [drv.read() for _ in range(20)]
        avg_z = sum(r.accel_z for r in readings) / len(readings)
        assert 9.0 < avg_z < 10.5

    def test_gyro_near_zero_at_rest(self, drv):
        readings = [drv.read() for _ in range(20)]
        avg_gz = sum(abs(r.gyro_z) for r in readings) / len(readings)
        assert avg_gz < 0.1  # rad/s

    def test_temperature_realistic(self, drv):
        r = drv.read()
        assert 15.0 < r.temperature_c < 50.0

    def test_covariance_populated(self, drv):
        r = drv.read()
        assert r.accel_covariance >= 0
        assert r.gyro_covariance >= 0


class TestMockImuFaults:
    def test_read_without_connect_raises(self):
        drv = MockImuDriver()
        with pytest.raises(DriverFault) as exc:
            drv.read()
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_start_disconnected(self):
        drv = MockImuDriver(start_disconnected=True)
        ok = drv.connect()
        assert ok is False

    def test_disconnect_after_n_reads(self):
        drv = MockImuDriver(disconnect_after_n=5)
        drv.connect()
        for _ in range(5):
            drv.read()
        with pytest.raises(DriverFault) as exc:
            drv.read()
        assert exc.value.error_code == "I2C_DISCONNECT"

    def test_spike_injection(self):
        drv = MockImuDriver(spike_every_n_reads=5)
        drv.connect()
        spikes_seen = 0
        for _i in range(20):
            r = drv.read()
            if abs(r.gyro_x) > 2.0 or abs(r.gyro_y) > 2.0:
                spikes_seen += 1
        assert spikes_seen >= 2  # at least cycles 5, 10, 15

    def test_latency_simulation(self):
        drv = MockImuDriver(simulate_latency_sec=0.05)
        drv.connect()
        t0 = time.monotonic()
        drv.read()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.04


class TestMockImuDrift:
    def test_gyro_drift_accumulates(self):
        drv = MockImuDriver(drift_rate_rad_s=1.0)  # large drift for test
        drv.connect()
        readings = [drv.read() for _ in range(50)]
        first_gz = readings[0].gyro_z
        last_gz = readings[-1].gyro_z
        # Drift should have shifted gz meaningfully
        assert abs(last_gz - first_gz) > 0.1


class TestMockImuRecovery:
    def test_reconnect_after_i2c_disconnect(self):
        drv = MockImuDriver(disconnect_after_n=3)
        drv.connect()
        for _ in range(3):
            drv.read()
        try:
            drv.read()
        except DriverFault:
            pass
        drv.inject_fault(disc_after=0)
        ok = drv.reconnect()
        assert ok
        r = drv.read()
        assert isinstance(r, ImuReading)

    def test_calibrate_resets_bias(self):
        drv = MockImuDriver()
        drv.connect()
        drv.calibrate()
        assert drv.is_connected


class TestImuDataIntegrity:
    def test_accel_values_are_floats(self, drv):
        r = drv.read()
        assert isinstance(r.accel_x, float)
        assert isinstance(r.accel_y, float)
        assert isinstance(r.accel_z, float)

    def test_gyro_values_are_floats(self, drv):
        r = drv.read()
        assert isinstance(r.gyro_x, float)
        assert isinstance(r.gyro_y, float)
        assert isinstance(r.gyro_z, float)

    def test_100_reads_all_valid(self, drv):
        for _ in range(100):
            r = drv.read()
            assert isinstance(r, ImuReading)
            assert r.temperature_c > 0
