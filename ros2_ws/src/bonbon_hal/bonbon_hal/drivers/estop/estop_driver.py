"""Abstract emergency-stop hardware driver."""

from __future__ import annotations

import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class EstopState:
    pressed: bool = False
    relay_asserted: bool = False  # True = motor power CUT
    input_pin: int = 17  # BCM GPIO pin
    relay_pin: int = 18
    timestamp: float = field(default_factory=time.monotonic)


class EstopDriver(DriverBase):
    """
    Hardware e-stop driver interface.

    The e-stop has two hardware elements:
      1. Input pin (BCM 17, active LOW) — reads the physical button.
      2. Relay output pin (BCM 18, active HIGH) — asserts to cut 24V motor power.

    The hardware button has its own direct relay path (belt-and-suspenders).
    The software relay assertion here is an additional software-controlled cut.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("estop", **kwargs)
        self._press_callback: Callable[[bool], None] | None = None

    @abstractmethod
    def read_state(self) -> EstopState:
        """Read current e-stop button and relay state."""

    @abstractmethod
    def assert_relay(self) -> None:
        """Assert the relay to physically cut 24V motor power."""

    @abstractmethod
    def deassert_relay(self) -> None:
        """De-assert the relay to restore 24V motor power."""

    def register_press_callback(self, cb: Callable[[bool], None]) -> None:
        """
        Register a callback fired on e-stop state change.
        cb(pressed: bool) — True = button just pressed, False = released.
        """
        self._press_callback = cb

    def _fire_press_callback(self, pressed: bool) -> None:
        if self._press_callback:
            try:
                self._press_callback(pressed)
            except Exception:
                pass
