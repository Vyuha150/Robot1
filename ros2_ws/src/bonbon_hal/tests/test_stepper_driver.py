"""Tests for MockStepperDriver: motion, fault injection, torque control,
stall clearing -- mirrors test_servo_driver.py / test_motor_driver.py."""

from __future__ import annotations

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.stepper import MockStepperDriver, StepperCommand


@pytest.fixture
def drv() -> MockStepperDriver:
    d = MockStepperDriver(stepper_ids=[1, 2])
    d.connect()
    return d


class TestMockStepperNormal:
    def test_connect_ok(self, drv):
        assert drv.is_connected

    def test_initial_position_is_zero(self, drv):
        r = drv.read_stepper(1)
        assert r.position_rad == 0.0
        assert r.is_stalled is False
        assert r.lost_sync is False
        assert r.enabled is True

    def test_write_command_moves_to_target(self, drv):
        drv.write_command(StepperCommand(stepper_id=1, target_position_rad=1.5))
        r = drv.read_stepper(1)
        assert r.position_rad == 1.5

    def test_write_commands_batch(self, drv):
        drv.write_commands(
            [
                StepperCommand(stepper_id=1, target_position_rad=0.5),
                StepperCommand(stepper_id=2, target_position_rad=-0.5),
            ]
        )
        assert drv.read_stepper(1).position_rad == 0.5
        assert drv.read_stepper(2).position_rad == -0.5

    def test_read_all_returns_every_stepper(self, drv):
        readings = drv.read_all()
        assert {r.stepper_id for r in readings} == {1, 2}

    def test_disabled_stepper_ignores_command(self, drv):
        drv.enable_torque(1, False)
        drv.write_command(StepperCommand(stepper_id=1, target_position_rad=2.0))
        assert drv.read_stepper(1).position_rad == 0.0

    def test_enable_all_torque(self, drv):
        drv.enable_all_torque(False)
        assert drv.read_stepper(1).enabled is False
        assert drv.read_stepper(2).enabled is False


class TestMockStepperFaults:
    def test_read_without_connect_raises(self):
        d = MockStepperDriver()
        with pytest.raises(DriverFault) as exc:
            d.read_stepper(1)
        assert exc.value.error_code == "NOT_CONNECTED"

    def test_start_disconnected(self):
        d = MockStepperDriver(start_disconnected=True)
        assert d.connect() is False

    def test_unknown_stepper_id_raises(self, drv):
        with pytest.raises(DriverFault) as exc:
            drv.read_stepper(99)
        assert exc.value.error_code == "INVALID_ID"

    def test_stalled_stepper_reports_lost_sync(self, drv):
        drv.inject_fault(stalled_id=1)
        r = drv.read_stepper(1)
        assert r.is_stalled is True
        assert r.lost_sync is True

    def test_write_command_to_stalled_stepper_raises(self, drv):
        drv.inject_fault(stalled_id=1)
        with pytest.raises(DriverFault) as exc:
            drv.write_command(StepperCommand(stepper_id=1, target_position_rad=1.0))
        assert exc.value.error_code == "STALLED"

    def test_stall_does_not_affect_other_steppers(self, drv):
        drv.inject_fault(stalled_id=1)
        drv.write_command(StepperCommand(stepper_id=2, target_position_rad=0.7))
        assert drv.read_stepper(2).position_rad == 0.7
        assert drv.read_stepper(2).lost_sync is False

    def test_clear_stall_resets_lost_sync_once_fault_condition_is_gone(self, drv):
        drv.inject_fault(stalled_id=1)
        drv.read_stepper(1)  # observe the stall
        drv.inject_fault(stalled_id=-1)  # underlying fault condition clears
        drv.clear_stall(1)
        assert drv.read_stepper(1).lost_sync is False

    def test_clear_stall_is_reasserted_while_fault_condition_persists(self, drv):
        drv.inject_fault(stalled_id=1)
        drv.read_stepper(1)  # observe the stall
        drv.clear_stall(1)
        # Real hardware: clear_stall() only acknowledges -- if the
        # physical jam/misalignment is still present, the alarm re-fires
        # on the next poll. The mock models that by re-injecting
        # lost_sync=True as long as stalled_id is still set.
        assert drv.read_stepper(1).lost_sync is True

    def test_stall_reaches_hal_fault_callback_via_read_stepper(self, drv):
        # Regression test: a stall must surface via _record_partial_fault()
        # (fires the HAL fault callback feeding /bonbon/hal/fault) on the
        # path that's actually polled every cycle -- read_stepper()/
        # read_all() -- not only when a new command happens to be written
        # to the stalled joint. Before this fix, an idle stalled joint
        # never emitted a HalFault at all.
        faults: list[tuple[str, str, str]] = []
        drv.register_fault_callback(lambda device, code, msg: faults.append((device, code, msg)))
        drv.inject_fault(stalled_id=1)
        drv.read_stepper(1)
        assert faults, "stall must fire the fault callback via read_stepper()"
        assert faults[-1][1] == "STALLED"
        # The bus itself is fine -- a single stalled joint must NOT mark
        # the whole driver disconnected (that would block reads of every
        # other channel and trigger a pointless reconnect loop).
        assert drv.is_connected is True
        assert drv.health.total_faults >= 1

    def test_stall_reaches_hal_fault_callback_via_read_all(self, drv):
        faults: list[tuple[str, str, str]] = []
        drv.register_fault_callback(lambda device, code, msg: faults.append((device, code, msg)))
        drv.inject_fault(stalled_id=2)
        drv.read_all()
        assert faults
        assert faults[-1][1] == "STALLED"

    def test_stall_on_one_channel_does_not_block_reads_of_other_channel(self, drv):
        drv.inject_fault(stalled_id=1)
        drv.read_stepper(1)  # observe the stall on channel 1
        # Channel 2 must still be readable -- the driver as a whole is
        # not disconnected by a single joint's mechanical stall.
        r2 = drv.read_stepper(2)
        assert r2.lost_sync is False

    def test_no_stall_keeps_recording_success(self, drv):
        drv.read_all()
        assert drv.health.consecutive_errors == 0
        assert drv.health.total_faults == 0


if __name__ == "__main__":
    pytest.main([__file__])
