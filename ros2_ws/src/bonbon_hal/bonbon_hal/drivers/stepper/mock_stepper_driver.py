"""MockStepperDriver — simulated closed-loop stepper for dev/CI, mirroring
MockServoDriver/MockMotorDriver's fault-injection conventions. Simulates
instantaneous step-to-target motion (gesture-speed steppers settle fast
enough that this is a reasonable test double) and lets tests force a
stall via inject_fault(stalled_id=...)."""

from __future__ import annotations

import time

from bonbon_hal.base.driver_base import DriverFault

from .stepper_driver import StepperCommand, StepperDriver, StepperReading


class MockStepperDriver(StepperDriver):
    def __init__(
        self,
        stepper_ids: list[int] | None = None,
        start_disconnected: bool = False,
        stalled_id: int = -1,
    ) -> None:
        ids = stepper_ids or [1, 2]
        super().__init__(stepper_ids=ids, driver_mode="mock")
        self._start_disc = start_disconnected
        self._stalled_id = stalled_id
        self._position: dict[int, float] = {sid: 0.0 for sid in ids}
        self._enabled: dict[int, bool] = {sid: True for sid in ids}
        self._lost_sync: dict[int, bool] = {sid: False for sid in ids}

    def _do_connect(self) -> bool:
        return not self._start_disc

    def _do_disconnect(self) -> None:
        pass

    def _check(self) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")

    def read_all(self) -> list[StepperReading]:
        self._check()
        readings = [self._reading(sid) for sid in self.stepper_ids]
        self._record_stall_or_success([r for r in readings if r.lost_sync])
        return readings

    def read_stepper(self, stepper_id: int) -> StepperReading:
        self._check()
        if stepper_id not in self._position:
            raise DriverFault(f"Unknown stepper {stepper_id}", "INVALID_ID")
        reading = self._reading(stepper_id)
        self._record_stall_or_success([reading] if reading.lost_sync else [])
        return reading

    def _record_stall_or_success(self, stalled: list[StepperReading]) -> None:
        # Mirrors the real NEMA17ClosedLoopDriver fix: a stall must reach
        # _record_partial_fault() (fires the HAL fault callback without
        # marking the whole multi-channel driver disconnected) on every
        # poll while it persists, not just _record_success() -- otherwise
        # an idle stalled joint never surfaces on /bonbon/hal/fault, and
        # using _record_fault() instead would incorrectly block reads of
        # every OTHER (non-stalled) channel on the same driver.
        if stalled:
            ids = ",".join(str(r.stepper_id) for r in stalled)
            self._record_partial_fault(
                "STALLED", f"stepper(s) {ids} lost sync — clear_stall() required"
            )
        else:
            self._record_success()

    def _reading(self, stepper_id: int) -> StepperReading:
        stalled = stepper_id == self._stalled_id
        if stalled:
            self._lost_sync[stepper_id] = True
        return StepperReading(
            stepper_id=stepper_id,
            position_rad=self._position[stepper_id],
            velocity_rads=0.0,
            is_stalled=stalled,
            lost_sync=self._lost_sync[stepper_id],
            enabled=self._enabled[stepper_id],
        )

    def write_command(self, cmd: StepperCommand) -> None:
        self._check()
        if cmd.stepper_id not in self._position:
            raise DriverFault(f"Unknown stepper {cmd.stepper_id}", "INVALID_ID")
        if cmd.stepper_id == self._stalled_id:
            self._lost_sync[cmd.stepper_id] = True
            raise DriverFault(f"Stepper {cmd.stepper_id} stalled", "STALLED")
        if self._enabled[cmd.stepper_id]:
            self._position[cmd.stepper_id] = cmd.target_position_rad

    def write_commands(self, cmds: list[StepperCommand]) -> None:
        self._check()
        for cmd in cmds:
            if cmd.stepper_id in self._position and self._enabled[cmd.stepper_id]:
                if cmd.stepper_id == self._stalled_id:
                    self._lost_sync[cmd.stepper_id] = True
                    continue
                self._position[cmd.stepper_id] = cmd.target_position_rad

    def enable_torque(self, stepper_id: int, enabled: bool) -> None:
        if stepper_id in self._enabled:
            self._enabled[stepper_id] = enabled

    def enable_all_torque(self, enabled: bool) -> None:
        for sid in self._enabled:
            self._enabled[sid] = enabled

    def clear_stall(self, stepper_id: int) -> None:
        if stepper_id in self._lost_sync:
            self._lost_sync[stepper_id] = False

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
