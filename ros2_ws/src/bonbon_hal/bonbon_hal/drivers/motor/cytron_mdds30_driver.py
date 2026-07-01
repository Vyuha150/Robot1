"""Cytron SmartDrive MDDS30 dual 30A motor driver (Pi-3 hardware -- Rhino
24V 60RPM 100W drive motors). See docs/HARDWARE_SOFTWARE_GAP_REPORT.md
item 1 (the single most severe finding in the Phase 1 audit: no driver
for this hardware existed anywhere in the repo).

Protocol: Cytron's documented "Simplified Serial Interface" -- a single
byte per motor over UART:
    0x00-0x7F (0-127):   Motor 1 (left).  0=full reverse, 63/64=stop, 127=full forward
    0x80-0xFF (128-255):  Motor 2 (right). 128=full reverse, 191/192=stop, 255=full forward
Default baud rate 115200 8N1 (matches Cytron's documented default).

SDK dependency: pyserial (pip install pyserial). Lazy import, same
honest-gap pattern as every other real driver in this repo (OrbbecDriver,
RplidarDriver, OAKDLiteDriver): if pyserial is missing, connect() fails
honestly via DriverFault rather than pretending to succeed.

No encoder feedback: the MDDS30 itself reports no wheel encoder ticks --
that would come from encoders on the Rhino motors/wheels if fitted, which
is a separate, not-yet-confirmed piece of hardware. read_wheels() here
therefore returns an OPEN-LOOP estimate (integrates the last commanded
speed over elapsed time) and reports has_encoders=False -- never fabricated
closed-loop odometry. If real encoders are confirmed present during Pi-3
hardware bring-up, this driver's read_wheels() must be upgraded to read
them; that is explicitly flagged here as future work, not assumed done.
"""

from __future__ import annotations

import logging
import time

from bonbon_hal.base.driver_base import DriverFault

from .motor_driver import MotorDriver, WheelCommand, WheelReading

logger = logging.getLogger(__name__)

_HAS_SERIAL = False
try:
    import serial  # type: ignore[import]

    _HAS_SERIAL = True
except ImportError:
    pass

_M1_MIN, _M1_STOP, _M1_MAX = 0, 64, 127
_M2_MIN, _M2_STOP, _M2_MAX = 128, 192, 255


def _speed_to_byte(speed_mps: float, max_speed_mps: float, lo: int, stop: int, hi: int) -> int:
    """Map a signed speed in [-max_speed_mps, +max_speed_mps] to the
    documented byte range for one channel, clamping out-of-range input
    rather than wrapping or raising -- a speed request that exceeds the
    configured max is capped, never silently misinterpreted."""
    if max_speed_mps <= 0:
        return stop
    frac = max(-1.0, min(1.0, speed_mps / max_speed_mps))
    if frac >= 0:
        return stop + round(frac * (hi - stop))
    return stop + round(frac * (stop - lo))


class CytronMDDS30Driver(MotorDriver):
    def __init__(
        self,
        port: str = "/dev/ttyUSB2",
        baudrate: int = 115200,
        max_speed_mps: float = 1.0,
        serial_timeout_sec: float = 0.2,
    ) -> None:
        super().__init__(max_speed_mps=max_speed_mps, has_encoders=False, driver_mode="real")
        self._port = port
        self._baudrate = baudrate
        self._serial_timeout = serial_timeout_sec
        self._ser = None

        self._last_command = WheelCommand(0.0, 0.0)
        self._last_command_ts = time.monotonic()
        self._left_distance_m = 0.0
        self._right_distance_m = 0.0

        if not _HAS_SERIAL:
            logger.warning(
                "pyserial not found — CytronMDDS30Driver will fail to connect. "
                "Install with: pip install pyserial"
            )

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_SERIAL:
            raise DriverFault("pyserial not installed", "SDK_MISSING", recoverable=False)
        try:
            self._ser = serial.Serial(
                port=self._port, baudrate=self._baudrate, timeout=self._serial_timeout
            )
            # Command a stop immediately on connect -- never start with an
            # undefined/leftover motor state.
            self._write_stop()
            self._last_command_ts = time.monotonic()
            logger.info("CytronMDDS30Driver: connected on %s @ %d baud", self._port, self._baudrate)
            return True
        except Exception as exc:
            raise DriverFault(f"serial open failed: {exc}", "SERIAL_OPEN_FAILED") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._ser is not None:
                self._write_stop()
                self._ser.close()
        except Exception as exc:
            logger.warning("CytronMDDS30Driver disconnect error: %s", exc)
        finally:
            self._ser = None

    # ── MotorDriver ──────────────────────────────────────────────────────────

    def set_wheel_speeds(self, command: WheelCommand) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            now = time.monotonic()
            dt = now - self._last_command_ts
            # Open-loop distance integration using the PREVIOUS command's
            # speed over the interval it was actually in effect.
            self._left_distance_m += self._last_command.left_mps * dt
            self._right_distance_m += self._last_command.right_mps * dt

            b1 = _speed_to_byte(command.left_mps, self.max_speed_mps, _M1_MIN, _M1_STOP, _M1_MAX)
            b2 = _speed_to_byte(command.right_mps, self.max_speed_mps, _M2_MIN, _M2_STOP, _M2_MAX)
            self._ser.write(bytes([b1, b2]))

            self._last_command = command
            self._last_command_ts = now
            self._record_success()
        except Exception as exc:
            self._record_fault("WRITE_ERROR", str(exc))
            raise DriverFault(f"Write failed: {exc}", "WRITE_ERROR") from exc

    def read_wheels(self) -> WheelReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        # Open-loop estimate only -- see module docstring. Distance since
        # the last set_wheel_speeds() call is accounted for at read time so
        # a read between commands still reflects elapsed motion.
        now = time.monotonic()
        dt = now - self._last_command_ts
        return WheelReading(
            left_mps=self._last_command.left_mps,
            right_mps=self._last_command.right_mps,
            left_distance_m=self._left_distance_m + self._last_command.left_mps * dt,
            right_distance_m=self._right_distance_m + self._last_command.right_mps * dt,
        )

    def emergency_stop(self) -> None:
        try:
            self._write_stop()
            self._last_command = WheelCommand(0.0, 0.0)
            self._last_command_ts = time.monotonic()
        except Exception as exc:  # noqa: BLE001 — e-stop path must never raise
            logger.error("CytronMDDS30Driver emergency_stop failed: %s", exc)

    def _write_stop(self) -> None:
        if self._ser is not None:
            self._ser.write(bytes([_M1_STOP, _M2_STOP]))
