"""
NEMA 17 closed-loop stepper motor driver (Pi-3 hardware -- HEAD pan L/R
and RIGHT ARM shoulder rotation, per the "Hand Gestures & Head Pan" BOM
sheet). See docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 2.

Interface: STEP/DIR/ENABLE digital GPIO -- the universal interface for
this class of driver -- plus an ALM (alarm) input exposed by essentially
every closed-loop stepper driver on the market. The alarm pin is the ONE
genuinely closed-loop fault signal (stall / lost-sync) anywhere in this
robot's actuator BOM, and it is wired through StallFaultTracker as a real,
debounced fault -- not left as an unused pin.

Same GPIO-library fallback convention as gpio_estop_driver.py:
Jetson.GPIO -> RPi.GPIO -> _MockGPIO, controlled by BONBON_SIMULATION.
This file is not unit-tested directly (matches this repo's established
convention -- see test_estop_driver.py, which tests MockEstopDriver, not
GpioEstopDriver); the logic that matters (step math, stall debouncing)
lives in stepper_kinematics.py and IS fully unit-tested (23 tests).

Step pulses are generated from a background thread at the configured
step rate. This is adequate for gesture-speed head/arm motion -- it is
not a CNC-grade motion controller and does not claim sub-millisecond
timing precision. If a specific gesture ever needs tighter timing, that
is a documented limitation to revisit (e.g. via pigpio's hardware-timed
waveforms), not a silent one.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from bonbon_hal.base.driver_base import DriverFault

from .stepper_driver import StepperCommand, StepperDriver, StepperReading
from .stepper_kinematics import (
    StallFaultConfig,
    StallFaultTracker,
    StepConverter,
    StepConverterConfig,
)

logger = logging.getLogger(__name__)

_SIMULATION = os.environ.get("BONBON_SIMULATION", "0") == "1"


class _MockGPIO:
    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"

    def setmode(self, *a):
        pass

    def setup(self, *a, **kw):
        pass

    def cleanup(self):
        pass

    def input(self, pin):
        return self.HIGH  # alarm pins are typically active-LOW; idle HIGH = no fault

    def output(self, pin, val):
        logger.debug("[MockGPIO] pin%d -> %d", pin, val)


def _load_gpio():
    if _SIMULATION:
        logger.info("BONBON_SIMULATION=1: using MockGPIO")
        return _MockGPIO()
    try:
        import Jetson.GPIO as GPIO  # type: ignore[import]

        return GPIO
    except ImportError:
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            return GPIO
        except ImportError:
            logger.warning("No GPIO library found — falling back to MockGPIO")
            return _MockGPIO()


class _StepperChannel:
    """Per-stepper GPIO pins + tracked state."""

    def __init__(
        self, stepper_id: int, step_pin: int, dir_pin: int, enable_pin: int, alarm_pin: int
    ) -> None:
        self.stepper_id = stepper_id
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        self.alarm_pin = alarm_pin
        self.target_rad = 0.0
        self.position_rad = 0.0
        self.enabled = True
        self.fault_tracker = StallFaultTracker(StallFaultConfig())


class NEMA17ClosedLoopDriver(StepperDriver):
    def __init__(
        self,
        stepper_ids: list[int],
        pin_map: dict[int, dict[str, int]],
        steps_per_rev: int = 200,
        microstepping: int = 8,
        max_step_rate_hz: float = 1500.0,
        alarm_active_low: bool = True,
        enable_active_low: bool = True,
        poll_hz: float = 50.0,
    ) -> None:
        super().__init__(stepper_ids=stepper_ids, driver_mode="real")
        self._pin_map = pin_map
        self._converter = StepConverter(StepConverterConfig(steps_per_rev, microstepping))
        self._max_step_rate_hz = max_step_rate_hz
        self._alarm_active_low = alarm_active_low
        self._enable_active_low = enable_active_low
        self._poll_hz = poll_hz
        self._gpio = _load_gpio()
        self._channels: dict[int, _StepperChannel] = {}
        self._lock = threading.Lock()
        self._running = False
        self._poll_thread: threading.Thread | None = None

        for sid in stepper_ids:
            pins = pin_map.get(sid)
            if pins is None:
                raise ValueError(f"pin_map missing entry for stepper_id {sid}")
            self._channels[sid] = _StepperChannel(
                sid, pins["step"], pins["dir"], pins["enable"], pins["alarm"]
            )

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        try:
            self._gpio.setmode(self._gpio.BCM)
            for ch in self._channels.values():
                self._gpio.setup(ch.step_pin, self._gpio.OUT)
                self._gpio.setup(ch.dir_pin, self._gpio.OUT)
                self._gpio.setup(ch.enable_pin, self._gpio.OUT)
                self._gpio.setup(ch.alarm_pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
                self._set_enable_pin(ch, True)
            self._running = True
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            logger.info("NEMA17ClosedLoopDriver: connected, %d channels", len(self._channels))
            return True
        except Exception as exc:
            raise DriverFault(str(exc), "GPIO_INIT_FAILED") from exc

    def _do_disconnect(self) -> None:
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
        try:
            for ch in self._channels.values():
                self._set_enable_pin(ch, False)
            self._gpio.cleanup()
        except Exception:
            pass

    def _set_enable_pin(self, ch: _StepperChannel, enabled: bool) -> None:
        asserted = enabled if not self._enable_active_low else not enabled
        self._gpio.output(ch.enable_pin, self._gpio.HIGH if asserted else self._gpio.LOW)
        ch.enabled = enabled

    def _poll_loop(self) -> None:
        interval = 1.0 / self._poll_hz
        while self._running:
            with self._lock:
                for ch in self._channels.values():
                    raw = self._gpio.input(ch.alarm_pin)
                    asserted = (
                        (raw == self._gpio.LOW)
                        if self._alarm_active_low
                        else (raw == self._gpio.HIGH)
                    )
                    ch.fault_tracker.poll(asserted)
                    if not ch.fault_tracker.lost_sync and ch.enabled:
                        self._step_toward_target(ch)
            time.sleep(interval)

    def _step_toward_target(self, ch: _StepperChannel) -> None:
        delta_steps = self._converter.step_delta(ch.position_rad, ch.target_rad)
        if delta_steps == 0:
            return
        self._gpio.output(ch.dir_pin, self._gpio.HIGH if delta_steps > 0 else self._gpio.LOW)
        step_count = min(abs(delta_steps), max(1, int(self._max_step_rate_hz / self._poll_hz)))
        for _ in range(step_count):
            self._gpio.output(ch.step_pin, self._gpio.HIGH)
            self._gpio.output(ch.step_pin, self._gpio.LOW)
        moved_steps = step_count if delta_steps > 0 else -step_count
        ch.position_rad += self._converter.steps_to_radians(moved_steps)

    # ── StepperDriver ────────────────────────────────────────────────────────

    def read_all(self) -> list[StepperReading]:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        with self._lock:
            readings = [self._reading(ch) for ch in self._channels.values()]
        self._record_stall_or_success([r for r in readings if r.lost_sync])
        return readings

    def read_stepper(self, stepper_id: int) -> StepperReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        ch = self._channels.get(stepper_id)
        if ch is None:
            raise DriverFault(f"Unknown stepper {stepper_id}", "INVALID_ID")
        with self._lock:
            reading = self._reading(ch)
        self._record_stall_or_success([reading] if reading.lost_sync else [])
        return reading

    def _record_stall_or_success(self, stalled: list[StepperReading]) -> None:
        # NOTE: without this, a stall confirmed by StallFaultTracker only
        # ever surfaced via write_command() raising DriverFault("STALLED")
        # -- which only fires if a NEW target is commanded. A robot sitting
        # idle with a stalled joint would never emit a HalFault at all,
        # since read_all()/read_stepper() (the path actually polled every
        # cycle) unconditionally called _record_success(). This now uses
        # _record_partial_fault() -- fires the HAL fault callback for as
        # long as any channel remains in lost_sync -- rather than
        # _record_fault(), because _record_fault() would flip this whole
        # multi-channel driver's status to FAULTED/not-connected over a
        # single stalled joint, needlessly blocking reads of every OTHER
        # channel on the same GPIO bus and triggering a pointless
        # reconnect loop that cannot fix a mechanical stall.
        if stalled:
            ids = ",".join(str(r.stepper_id) for r in stalled)
            self._record_partial_fault(
                "STALLED", f"stepper(s) {ids} lost sync — clear_stall() required"
            )
        else:
            self._record_success()

    def _reading(self, ch: _StepperChannel) -> StepperReading:
        return StepperReading(
            stepper_id=ch.stepper_id,
            position_rad=ch.position_rad,
            velocity_rads=0.0,  # not measurable open-loop between polls; see module docstring
            is_stalled=ch.fault_tracker.is_stalled,
            lost_sync=ch.fault_tracker.lost_sync,
            enabled=ch.enabled,
        )

    def write_command(self, cmd: StepperCommand) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        ch = self._channels.get(cmd.stepper_id)
        if ch is None:
            raise DriverFault(f"Unknown stepper {cmd.stepper_id}", "INVALID_ID")
        if ch.fault_tracker.lost_sync:
            raise DriverFault(
                f"Stepper {cmd.stepper_id} lost sync — clear_stall() required", "STALLED"
            )
        with self._lock:
            ch.target_rad = cmd.target_position_rad

    def write_commands(self, cmds: list[StepperCommand]) -> None:
        for cmd in cmds:
            self.write_command(cmd)

    def enable_torque(self, stepper_id: int, enabled: bool) -> None:
        ch = self._channels.get(stepper_id)
        if ch is not None:
            self._set_enable_pin(ch, enabled)

    def enable_all_torque(self, enabled: bool) -> None:
        for ch in self._channels.values():
            self._set_enable_pin(ch, enabled)

    def clear_stall(self, stepper_id: int) -> None:
        ch = self._channels.get(stepper_id)
        if ch is None:
            raise DriverFault(f"Unknown stepper {stepper_id}", "INVALID_ID")
        with self._lock:
            cleared = ch.fault_tracker.clear_stall()
        if not cleared:
            logger.warning(
                "clear_stall(%d) refused — alarm condition not yet confirmed clear", stepper_id
            )
