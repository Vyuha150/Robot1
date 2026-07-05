"""Tests for PCA9685ServoDriver's pure math (angle<->pulse-width
conversion) and its honest no-SDK-installed behavior. smbus2 is genuinely
not installed in this sandbox, so the SDK_MISSING assertions are real,
not mocked (mirrors test_oakd_lite_driver.py / test_cytron_mdds30's
pattern for the same reason).

The angle<->pulse conversion methods touch no I2C hardware at all, so
they're exercised directly against a driver instance that is never
connected -- no smbus2 needed for this part either.
"""

from __future__ import annotations

import math

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.servo.pca9685_servo_driver import (
    _HAS_SMBUS,
    PCA9685ServoDriver,
    ServoCalibration,
)


def _make_driver(**cal_overrides) -> PCA9685ServoDriver:
    cal = ServoCalibration(channel=0, **cal_overrides)
    return PCA9685ServoDriver(servo_ids=[1], calibrations={1: cal})


class TestNoSDK:
    def test_sdk_not_installed_in_this_environment(self):
        assert _HAS_SMBUS is False

    def test_connect_fails_honestly_when_sdk_missing(self):
        drv = _make_driver()
        assert drv.connect() is False

    def test_read_without_connect_raises_not_connected(self):
        drv = _make_driver()
        with pytest.raises(DriverFault) as exc:
            drv.read_servo(1)
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_unknown_calibration_raises_at_construction(self):
        with pytest.raises(ValueError):
            PCA9685ServoDriver(servo_ids=[1, 2], calibrations={1: ServoCalibration(channel=0)})


class TestAngleToPulseConversion:
    def test_min_angle_maps_to_min_pulse(self):
        drv = _make_driver(
            min_angle_rad=0.0, max_angle_rad=math.pi, min_pulse_us=1000.0, max_pulse_us=2000.0
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, 0.0) == pytest.approx(1000.0)

    def test_max_angle_maps_to_max_pulse(self):
        drv = _make_driver(
            min_angle_rad=0.0, max_angle_rad=math.pi, min_pulse_us=1000.0, max_pulse_us=2000.0
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, math.pi) == pytest.approx(2000.0)

    def test_midpoint_angle_maps_to_midpoint_pulse(self):
        drv = _make_driver(
            min_angle_rad=0.0, max_angle_rad=math.pi, min_pulse_us=1000.0, max_pulse_us=2000.0
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, math.pi / 2) == pytest.approx(1500.0)

    def test_out_of_range_angle_clamped_not_extrapolated(self):
        drv = _make_driver(
            min_angle_rad=0.0, max_angle_rad=math.pi, min_pulse_us=1000.0, max_pulse_us=2000.0
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, -10.0) == pytest.approx(1000.0)
        assert drv._angle_to_pulse_us(cal, 10.0) == pytest.approx(2000.0)

    def test_invert_flips_the_mapping(self):
        drv = _make_driver(
            min_angle_rad=0.0,
            max_angle_rad=math.pi,
            min_pulse_us=1000.0,
            max_pulse_us=2000.0,
            invert=True,
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, 0.0) == pytest.approx(2000.0)
        assert drv._angle_to_pulse_us(cal, math.pi) == pytest.approx(1000.0)

    def test_custom_calibration_range_respected(self):
        drv = _make_driver(
            min_angle_rad=-1.0, max_angle_rad=1.0, min_pulse_us=800.0, max_pulse_us=2200.0
        )
        cal = drv._channels[1].calibration
        assert drv._angle_to_pulse_us(cal, -1.0) == pytest.approx(800.0)
        assert drv._angle_to_pulse_us(cal, 1.0) == pytest.approx(2200.0)
        assert drv._angle_to_pulse_us(cal, 0.0) == pytest.approx(1500.0)


class TestUnmeasurableFieldsAreHonest:
    def test_calibration_defaults_are_the_common_rc_servo_range(self):
        cal = ServoCalibration(channel=0)
        assert cal.min_pulse_us == 1000.0
        assert cal.max_pulse_us == 2000.0
        assert cal.min_angle_rad == 0.0
        assert cal.max_angle_rad == pytest.approx(math.pi, abs=1e-6)


if __name__ == "__main__":
    pytest.main([__file__])
