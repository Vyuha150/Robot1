"""Tests for the motor driver abstraction: MockMotorDriver (full behavior),
and CytronMDDS30Driver's speed->byte mapping + honest no-SDK gap (the
latter mirrors test_oakd_lite_driver.py's pattern -- pyserial genuinely
isn't installed in this sandbox, so these are real, not mocked, assertions).
"""

from __future__ import annotations

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.motor import CytronMDDS30Driver, MockMotorDriver, WheelCommand
from bonbon_hal.drivers.motor.cytron_mdds30_driver import _HAS_SERIAL, _speed_to_byte


class TestSpeedToByteMapping:
    """Pure function, no hardware needed -- verifies the documented Cytron
    Simplified Serial byte ranges exactly."""

    def test_full_reverse_left_channel(self):
        assert _speed_to_byte(-1.0, 1.0, 0, 64, 127) == 0

    def test_full_forward_left_channel(self):
        assert _speed_to_byte(1.0, 1.0, 0, 64, 127) == 127

    def test_stop_left_channel(self):
        assert _speed_to_byte(0.0, 1.0, 0, 64, 127) == 64

    def test_full_reverse_right_channel(self):
        assert _speed_to_byte(-1.0, 1.0, 128, 192, 255) == 128

    def test_full_forward_right_channel(self):
        assert _speed_to_byte(1.0, 1.0, 128, 192, 255) == 255

    def test_stop_right_channel(self):
        assert _speed_to_byte(0.0, 1.0, 128, 192, 255) == 192

    def test_half_speed_forward_is_between_stop_and_max(self):
        b = _speed_to_byte(0.5, 1.0, 0, 64, 127)
        assert 64 < b < 127

    def test_over_max_speed_clamped_not_wrapped(self):
        # Requesting 3x the configured max must clamp to full-forward byte,
        # never wrap around into the reverse range.
        assert _speed_to_byte(3.0, 1.0, 0, 64, 127) == 127

    def test_under_min_speed_clamped_not_wrapped(self):
        assert _speed_to_byte(-3.0, 1.0, 0, 64, 127) == 0

    def test_zero_max_speed_always_stops(self):
        assert _speed_to_byte(0.5, 0.0, 0, 64, 127) == 64


class TestCytronDriverNoSDK:
    def test_sdk_not_installed_in_this_environment(self):
        assert _HAS_SERIAL is False

    def test_connect_fails_honestly_when_sdk_missing(self):
        drv = CytronMDDS30Driver(port="/dev/ttyUSB2")
        assert drv.connect() is False

    def test_read_wheels_without_connect_raises(self):
        drv = CytronMDDS30Driver(port="/dev/ttyUSB2")
        with pytest.raises(DriverFault) as exc:
            drv.read_wheels()
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_has_encoders_is_honestly_false(self):
        # No confirmed wheel-encoder hardware -- must never claim closed-loop.
        drv = CytronMDDS30Driver(port="/dev/ttyUSB2")
        assert drv.has_encoders is False

    def test_emergency_stop_never_raises_even_when_disconnected(self):
        drv = CytronMDDS30Driver(port="/dev/ttyUSB2")
        drv.emergency_stop()  # must not raise


class TestMockMotorDriver:
    @pytest.fixture
    def drv(self):
        d = MockMotorDriver(max_speed_mps=1.0)
        d.connect()
        return d

    def test_connect_ok(self, drv):
        assert drv.is_connected

    def test_initial_wheels_are_stopped(self, drv):
        r = drv.read_wheels()
        assert r.left_mps == 0.0
        assert r.right_mps == 0.0

    def test_set_speed_reflected_in_read(self, drv):
        drv.set_wheel_speeds(WheelCommand(left_mps=0.5, right_mps=-0.3))
        r = drv.read_wheels()
        assert r.left_mps == 0.5
        assert r.right_mps == -0.3

    def test_distance_accumulates_over_time(self, drv):
        import time

        drv.set_wheel_speeds(WheelCommand(left_mps=1.0, right_mps=1.0))
        time.sleep(0.05)
        r = drv.read_wheels()
        assert r.left_distance_m > 0.0
        assert r.right_distance_m > 0.0

    def test_emergency_stop_zeroes_speed(self, drv):
        drv.set_wheel_speeds(WheelCommand(left_mps=1.0, right_mps=1.0))
        drv.emergency_stop()
        r = drv.read_wheels()
        assert r.left_mps == 0.0
        assert r.right_mps == 0.0

    def test_read_without_connect_raises(self):
        drv = MockMotorDriver()
        with pytest.raises(DriverFault) as exc:
            drv.read_wheels()
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_start_disconnected(self):
        drv = MockMotorDriver(start_disconnected=True)
        assert drv.connect() is False

    def test_fault_injection_after_n_commands(self):
        drv = MockMotorDriver(fail_after_n_commands=2)
        drv.connect()
        drv.set_wheel_speeds(WheelCommand(0.1, 0.1))
        drv.set_wheel_speeds(WheelCommand(0.1, 0.1))
        with pytest.raises(DriverFault) as exc:
            drv.set_wheel_speeds(WheelCommand(0.1, 0.1))
        assert exc.value.error_code == "SIMULATED_FAULT"

    def test_has_encoders_true_for_mock(self, drv):
        # Mock simulates a closed-loop system for test convenience --
        # distinct from the real Cytron driver's honest has_encoders=False.
        assert drv.has_encoders is True


if __name__ == "__main__":
    pytest.main([__file__])
