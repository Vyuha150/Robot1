"""
GPIO e-stop driver (Jetson Orin Nano / Raspberry Pi compatible).

Identical GPIO logic to bonbon_safety/nodes/estop_node.py but expressed
as a standalone DriverBase so it can be unit-tested and reused by the HAL
estop node without depending on the safety package.

Wiring (same as circuit blueprint):
  BCM 17 (input,  pull-up) ← e-stop button (active LOW)
  BCM 18 (output, active HIGH) → relay coil → 24V motor rail
"""

from __future__ import annotations

import logging
import os
import threading
import time

from bonbon_hal.base.driver_base import DriverFault

from .estop_driver import EstopDriver, EstopState

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
        return self.HIGH

    def output(self, pin, val):
        logger.debug("[MockGPIO] pin%d→%d", pin, val)


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


class GpioEstopDriver(EstopDriver):

    def __init__(
        self,
        input_pin: int = 17,
        relay_pin: int = 18,
        poll_hz: float = 50.0,
    ) -> None:
        super().__init__(driver_mode="real")
        self._in_pin = input_pin
        self._relay_pin = relay_pin
        self._poll_hz = poll_hz
        self._gpio = _load_gpio()
        self._pressed = False
        self._relay_on = False
        self._lock = threading.Lock()
        self._poll_thread: threading.Thread | None = None
        self._running = False

    def _do_connect(self) -> bool:
        try:
            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setup(self._in_pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
            self._gpio.setup(self._relay_pin, self._gpio.OUT)
            self._gpio.output(self._relay_pin, self._gpio.LOW)  # relay de-asserted
            self._running = True
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            logger.info(
                "GpioEstopDriver: polling at %.0f Hz, input=%d relay=%d",
                self._poll_hz,
                self._in_pin,
                self._relay_pin,
            )
            return True
        except Exception as exc:
            raise DriverFault(str(exc), "GPIO_INIT_FAILED") from exc

    def _do_disconnect(self) -> None:
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
        try:
            self._gpio.cleanup()
        except Exception:
            pass

    def _poll_loop(self) -> None:
        interval = 1.0 / self._poll_hz
        prev_pressed = False
        while self._running:
            raw = self._gpio.input(self._in_pin)
            pressed = raw == self._gpio.LOW  # active LOW
            with self._lock:
                self._pressed = pressed
            if pressed != prev_pressed:
                prev_pressed = pressed
                if pressed:
                    logger.fatal("E-STOP BUTTON PRESSED")
                else:
                    logger.warning("E-stop button released")
                self._fire_press_callback(pressed)
            self._record_success()
            time.sleep(interval)

    def read_state(self) -> EstopState:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        with self._lock:
            return EstopState(
                pressed=self._pressed,
                relay_asserted=self._relay_on,
                input_pin=self._in_pin,
                relay_pin=self._relay_pin,
            )

    def assert_relay(self) -> None:
        self._gpio.output(self._relay_pin, self._gpio.HIGH)
        self._relay_on = True
        logger.fatal("RELAY ASSERTED — 24V motor power CUT")

    def deassert_relay(self) -> None:
        self._gpio.output(self._relay_pin, self._gpio.LOW)
        self._relay_on = False
        logger.warning("RELAY DE-ASSERTED — 24V motor power RESTORED")
