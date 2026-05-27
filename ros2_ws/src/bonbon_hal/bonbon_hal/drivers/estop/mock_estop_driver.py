"""
Mock e-stop driver.

Allows tests to press/release the virtual e-stop button via
press() and release() methods.
"""

from __future__ import annotations

import time

from bonbon_hal.base.driver_base import DriverFault

from .estop_driver import EstopDriver, EstopState


class MockEstopDriver(EstopDriver):

    def __init__(
        self,
        start_pressed: bool = False,
        start_disconnected: bool = False,
        simulate_latency_sec: float = 0.0,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._pressed = start_pressed
        self._relay_asserted = False
        self._start_disc = start_disconnected
        self._latency = simulate_latency_sec

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.01)
        return True

    def _do_disconnect(self) -> None:
        pass

    def read_state(self) -> EstopState:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._latency:
            time.sleep(self._latency)
        self._record_success()
        return EstopState(
            pressed=self._pressed,
            relay_asserted=self._relay_asserted,
        )

    def assert_relay(self) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        self._relay_asserted = True

    def deassert_relay(self) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        self._relay_asserted = False

    # ── Test helpers ───────────────────────────────────────────────────────────

    def press(self) -> None:
        """Simulate operator pressing the e-stop button."""
        was = self._pressed
        self._pressed = True
        if not was:
            self._fire_press_callback(True)

    def release(self) -> None:
        """Simulate operator releasing the e-stop button."""
        was = self._pressed
        self._pressed = False
        if was:
            self._fire_press_callback(False)
