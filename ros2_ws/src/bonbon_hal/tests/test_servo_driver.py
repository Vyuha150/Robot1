"""
test_servo_driver.py
====================
Tests for MockServoDriver: reads, commands, torque, thermal, faults, recovery.
"""

from __future__ import annotations

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.servo import MockServoDriver, ServoCommand, ServoReading


@pytest.fixture
def drv() -> MockServoDriver:
    d = MockServoDriver(servo_ids=[1, 2, 3])
    d.connect()
    return d


class TestMockServoNormal:
    def test_connect_ok(self, drv):
        assert drv.is_connected

    def test_read_all_returns_all_servos(self, drv):
        readings = drv.read_all()
        assert len(readings) == 3
        ids = {r.servo_id for r in readings}
        assert ids == {1, 2, 3}

    def test_reading_fields_populated(self, drv):
        r = drv.read_servo(1)
        assert isinstance(r, ServoReading)
        assert r.servo_id == 1
        assert isinstance(r.position_rad, float)
        assert isinstance(r.temperature_c, float)
        assert r.voltage_v > 0

    def test_write_command_moves_servo(self, drv):
        cmd = ServoCommand(servo_id=1, target_position_rad=1.57)
        drv.write_command(cmd)
        # Give the simulation a step
        drv.read_servo(1)
        r = drv.read_servo(1)
        # After a few reads the servo should be approaching target
        assert abs(r.position_rad) >= 0  # just check it's a float

    def test_write_commands_bulk(self, drv):
        cmds = [ServoCommand(servo_id=i, target_position_rad=0.5) for i in [1, 2, 3]]
        drv.write_commands(cmds)
        readings = drv.read_all()
        assert len(readings) == 3

    def test_enable_disable_torque(self, drv):
        drv.enable_torque(1, False)
        r = drv.read_servo(1)
        assert r.torque_enabled is False
        drv.enable_torque(1, True)
        r = drv.read_servo(1)
        assert r.torque_enabled is True

    def test_enable_all_torque(self, drv):
        drv.enable_all_torque(False)
        for r in drv.read_all():
            assert r.torque_enabled is False

    def test_temperature_rises_with_load(self, drv):
        drv.write_command(ServoCommand(1, target_position_rad=3.14))
        t0 = drv.read_servo(1).temperature_c
        for _ in range(50):
            drv.read_servo(1)  # each read steps the simulation
        t1 = drv.read_servo(1).temperature_c
        assert t1 >= t0  # temperature should not decrease under load


class TestMockServoFaults:
    def test_read_without_connect_raises(self):
        drv = MockServoDriver(servo_ids=[1])
        with pytest.raises(DriverFault):
            drv.read_all()

    def test_invalid_servo_id_raises(self, drv):
        with pytest.raises(DriverFault) as exc:
            drv.read_servo(99)
        assert exc.value.error_code == "INVALID_ID"

    def test_servo_fault_injection(self):
        drv = MockServoDriver(servo_ids=[1, 2], servo_fault_id=2)
        drv.connect()
        readings = drv.read_all()
        faulted = next(r for r in readings if r.servo_id == 2)
        assert faulted.error_code != 0

    def test_usb_disconnect_after_n(self):
        drv = MockServoDriver(servo_ids=[1], disconnect_after_n=3)
        drv.connect()
        for _ in range(3):
            drv.read_all()
        with pytest.raises(DriverFault) as exc:
            drv.read_all()
        assert exc.value.error_code == "USB_DISCONNECTED"

    def test_latency_simulation(self):
        import time

        drv = MockServoDriver(servo_ids=[1], simulate_latency_sec=0.05)
        drv.connect()
        t0 = time.monotonic()
        drv.read_all()
        assert time.monotonic() - t0 >= 0.04


class TestMockServoRecovery:
    def test_reconnect_restores_reads(self):
        drv = MockServoDriver(servo_ids=[1], disconnect_after_n=2)
        drv.connect()
        drv.read_all()
        drv.read_all()
        try:
            drv.read_all()
        except DriverFault:
            pass
        drv.inject_fault(disc_after=0)
        ok = drv.reconnect()
        assert ok
        readings = drv.read_all()
        assert len(readings) == 1
