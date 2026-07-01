"""MockMotorDriver — simulated dual-channel motor for dev/CI/simulation,
mirroring MockCameraDriver/MockServoDriver's fault-injection conventions."""

from __future__ import annotations

import time

from bonbon_hal.base.driver_base import DriverFault

from .motor_driver import MotorDriver, WheelCommand, WheelReading


class MockMotorDriver(MotorDriver):
    def __init__(
        self,
        max_speed_mps: float = 1.0,
        start_disconnected: bool = False,
        fail_after_n_commands: int | None = None,
    ) -> None:
        super().__init__(max_speed_mps=max_speed_mps, has_encoders=True, driver_mode="mock")
        self._start_disconnected = start_disconnected
        self._fail_after_n_commands = fail_after_n_commands
        self._command_count = 0

        self._last_command = WheelCommand(0.0, 0.0)
        self._last_command_ts = time.monotonic()
        self._left_distance_m = 0.0
        self._right_distance_m = 0.0

    def _do_connect(self) -> bool:
        return not self._start_disconnected

    def _do_disconnect(self) -> None:
        self._last_command = WheelCommand(0.0, 0.0)

    def set_wheel_speeds(self, command: WheelCommand) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        self._command_count += 1
        if (
            self._fail_after_n_commands is not None
            and self._command_count > self._fail_after_n_commands
        ):
            self._record_fault("SIMULATED_FAULT", "injected test failure")
            raise DriverFault("Simulated motor fault", "SIMULATED_FAULT")

        now = time.monotonic()
        dt = now - self._last_command_ts
        self._left_distance_m += self._last_command.left_mps * dt
        self._right_distance_m += self._last_command.right_mps * dt
        self._last_command = command
        self._last_command_ts = now
        self._record_success()

    def read_wheels(self) -> WheelReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        now = time.monotonic()
        dt = now - self._last_command_ts
        return WheelReading(
            left_mps=self._last_command.left_mps,
            right_mps=self._last_command.right_mps,
            left_distance_m=self._left_distance_m + self._last_command.left_mps * dt,
            right_distance_m=self._right_distance_m + self._last_command.right_mps * dt,
        )

    def emergency_stop(self) -> None:
        self._last_command = WheelCommand(0.0, 0.0)
        self._last_command_ts = time.monotonic()
