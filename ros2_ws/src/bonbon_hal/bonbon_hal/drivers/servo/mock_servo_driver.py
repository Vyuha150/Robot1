"""
Mock Dynamixel servo driver.

Simulates realistic servo physics:
  - First-order position tracking with configurable time constant
  - Load proportional to position error
  - Temperature that rises with load and falls toward ambient

Fault injection:
  servo_fault_id         : servo ID to inject a hardware error
  disconnect_after_n     : simulate USB pull after N reads
  simulate_latency_sec   : artificial read latency
"""

from __future__ import annotations

import math
import random
import time

from bonbon_hal.base.driver_base import DriverFault

from .servo_driver import ServoCommand, ServoDriver, ServoReading


class _SimServo:
    """Simulates one Dynamixel's internal state."""

    def __init__(self, servo_id: int) -> None:
        self.id = servo_id
        self.target_rad = 0.0
        self.current_rad = 0.0
        self.velocity_rads = 0.0
        self.load_pct = 0.0
        self.temp_c = 28.0
        self.voltage_v = 12.0
        self.error_code = 0
        self.torque_on = True
        self._last_t = time.monotonic()
        self._vel_limit = 1.0  # rad/s
        self._tau = 0.2  # time constant s

    def step(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now
        if not self.torque_on:
            return
        err = self.target_rad - self.current_rad
        # First-order step
        alpha = 1.0 - math.exp(-dt / self._tau)
        self.velocity_rads = min(abs(err) / max(dt, 1e-6), self._vel_limit)
        self.velocity_rads = math.copysign(self.velocity_rads, err)
        self.current_rad += alpha * err
        self.load_pct = min(100.0, abs(err) * 50)
        # Thermal: rise with load, fall toward ambient
        self.temp_c += dt * (self.load_pct * 0.05 - (self.temp_c - 28.0) * 0.01)
        self.temp_c = max(28.0, self.temp_c)

    def reading(self) -> ServoReading:
        return ServoReading(
            servo_id=self.id,
            position_rad=self.current_rad,
            velocity_rads=self.velocity_rads,
            load_percent=self.load_pct,
            temperature_c=self.temp_c,
            voltage_v=self.voltage_v + random.gauss(0, 0.05),
            error_code=self.error_code,
            torque_enabled=self.torque_on,
        )


class MockServoDriver(ServoDriver):

    def __init__(
        self,
        servo_ids: list[int] = None,
        servo_fault_id: int = -1,
        disconnect_after_n: int = 0,
        simulate_latency_sec: float = 0.0,
        start_disconnected: bool = False,
    ) -> None:
        ids = servo_ids or [1, 2, 3, 4]
        super().__init__(servo_ids=ids, driver_mode="mock")
        self._fault_id = servo_fault_id
        self._disc_after = disconnect_after_n
        self._latency = simulate_latency_sec
        self._start_disc = start_disconnected
        self._read_count = 0
        self._servos: dict[int, _SimServo] = {sid: _SimServo(sid) for sid in ids}

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.05)
        return True

    def _do_disconnect(self) -> None:
        pass

    def _check(self) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._latency:
            time.sleep(self._latency)
        self._read_count += 1
        if self._disc_after > 0 and self._read_count > self._disc_after:
            self._record_fault("USB_DISCONNECTED", "Simulated USB disconnect")
            raise DriverFault("USB disconnect", "USB_DISCONNECTED")

    def read_all(self) -> list[ServoReading]:
        self._check()
        readings = []
        for servo in self._servos.values():
            servo.step()
            r = servo.reading()
            if servo.id == self._fault_id:
                r.error_code = 0x04  # Dynamixel overheating error
                r.temperature_c = 85.0
            readings.append(r)
        self._record_success()
        return readings

    def read_servo(self, servo_id: int) -> ServoReading:
        self._check()
        if servo_id not in self._servos:
            raise DriverFault(f"Unknown servo {servo_id}", "INVALID_ID")
        self._servos[servo_id].step()
        self._record_success()
        return self._servos[servo_id].reading()

    def write_command(self, cmd: ServoCommand) -> None:
        self._check()
        if cmd.servo_id not in self._servos:
            raise DriverFault(f"Unknown servo {cmd.servo_id}", "INVALID_ID")
        s = self._servos[cmd.servo_id]
        s.target_rad = cmd.target_position_rad
        s._vel_limit = cmd.velocity_limit_rads if cmd.velocity_limit_rads > 0 else 1.0

    def write_commands(self, cmds: list[ServoCommand]) -> None:
        self._check()
        for cmd in cmds:
            if cmd.servo_id in self._servos:
                s = self._servos[cmd.servo_id]
                s.target_rad = cmd.target_position_rad
                s._vel_limit = cmd.velocity_limit_rads if cmd.velocity_limit_rads > 0 else 1.0

    def enable_torque(self, servo_id: int, enabled: bool) -> None:
        if servo_id in self._servos:
            self._servos[servo_id].torque_on = enabled

    def enable_all_torque(self, enabled: bool) -> None:
        for s in self._servos.values():
            s.torque_on = enabled

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
