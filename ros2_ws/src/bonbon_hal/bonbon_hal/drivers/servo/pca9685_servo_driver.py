"""
PCA9685 16-channel I2C PWM driver — the correct real hardware for the
BOM's "25kgcm Metal Gear Digital Servo Motor - 180 degree" (RIGHT ARM
elbow, RIGHT ARM wrist, HEAD up/down). See
docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 7's supersession note: this
robot's servos are standard PWM RC servos, not Dynamixel smart servos
(DynamixelDriver remains a valid selectable backend for any future
Dynamixel hardware, but is NOT what's in this BOM).

SDK dependency: smbus2 (pip install smbus2) — same I2C library already
used by bonbon_hal's INA226 battery driver, chosen over the heavier
Adafruit Blinka stack (which does hardware/board auto-detection at import
time and can fail hard off-Pi) specifically so this module still imports
cleanly on a dev machine.

Honest limitation, documented not hidden: standard PWM RC servos have NO
feedback sensor. load_percent / temperature_c / voltage_v cannot be
measured and are reported as float('nan') ("not measurable"), never a
fabricated value — same honesty pattern as CytronMDDS30Driver's
has_encoders=False. position_rad is the last COMMANDED position (an
open-loop echo), not a measured one. torque_enabled/enable_torque() is a
real capability here: disabling torque stops the PWM pulse train on that
channel, which is exactly the effect of disabling holding torque on
these servos (some may go limp, some hold their last mechanical position
depending on gearing friction — a real, hardware-dependent behavior worth
confirming during Pi-3 bring-up, not assumed).

Register reference: NXP PCA9685 datasheet (16-channel, 12-bit PWM, I2C).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverFault

from .servo_driver import ServoCommand, ServoDriver, ServoReading

logger = logging.getLogger(__name__)

_HAS_SMBUS = False
try:
    import smbus2  # type: ignore[import]

    _HAS_SMBUS = True
except ImportError:
    pass

# PCA9685 registers
_MODE1 = 0x00
_MODE2 = 0x01
_PRESCALE = 0xFE
_LED0_ON_L = 0x06  # base address; each channel uses 4 consecutive registers

_MODE1_SLEEP = 0x10
_MODE1_AUTO_INCREMENT = 0x20
_MODE1_RESTART = 0x80
_MODE2_OUTDRV = 0x04  # totem-pole (push-pull) output, standard for servo PWM

_INTERNAL_OSC_HZ = 25_000_000
_PWM_RESOLUTION = 4096  # 12-bit


@dataclass(frozen=True)
class ServoCalibration:
    """Per-channel pulse-width calibration. Defaults are the common RC
    servo range (1000-2000us); the BOM's exact "25kgcm... 180 degree"
    servos should be measured against the physical hardware during
    Pi-3 bring-up rather than assumed to hit these defaults precisely."""

    channel: int
    min_pulse_us: float = 1000.0
    max_pulse_us: float = 2000.0
    min_angle_rad: float = 0.0
    max_angle_rad: float = 3.14159265  # 180 degrees
    invert: bool = False


@dataclass
class _ChannelState:
    calibration: ServoCalibration
    commanded_rad: float = 0.0
    torque_enabled: bool = True


class PCA9685ServoDriver(ServoDriver):
    def __init__(
        self,
        servo_ids: list[int],
        calibrations: dict[int, ServoCalibration],
        i2c_bus: int = 1,
        i2c_address: int = 0x40,
        pwm_freq_hz: float = 50.0,
    ) -> None:
        super().__init__(servo_ids=servo_ids, driver_mode="real")
        self._bus_num = i2c_bus
        self._addr = i2c_address
        self._freq = pwm_freq_hz
        self._bus_obj = None
        self._channels: dict[int, _ChannelState] = {}

        for sid in servo_ids:
            cal = calibrations.get(sid)
            if cal is None:
                raise ValueError(f"calibrations missing entry for servo_id {sid}")
            self._channels[sid] = _ChannelState(calibration=cal)

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_SMBUS:
            raise DriverFault("smbus2 not installed", "SDK_MISSING", recoverable=False)
        try:
            self._bus_obj = smbus2.SMBus(self._bus_num)
            self._set_pwm_freq(self._freq)
            for _sid, ch in self._channels.items():
                self._write_channel_us(ch.calibration.channel, 0.0)  # start every channel off
            logger.info(
                "PCA9685ServoDriver: connected on i2c-%d addr=0x%02X freq=%.1fHz, %d channels",
                self._bus_num,
                self._addr,
                self._freq,
                len(self._channels),
            )
            return True
        except Exception as exc:
            raise DriverFault(f"PCA9685 init failed: {exc}", "I2C_INIT_FAILED") from exc

    def _do_disconnect(self) -> None:
        try:
            for ch in self._channels.values():
                self._write_channel_us(ch.calibration.channel, 0.0)
            if self._bus_obj is not None:
                self._bus_obj.close()
        except Exception as exc:
            logger.warning("PCA9685ServoDriver disconnect error: %s", exc)
        finally:
            self._bus_obj = None

    def _write_reg(self, reg: int, value: int) -> None:
        self._bus_obj.write_byte_data(self._addr, reg, value)

    def _read_reg(self, reg: int) -> int:
        return self._bus_obj.read_byte_data(self._addr, reg)

    def _set_pwm_freq(self, freq_hz: float) -> None:
        prescale = round(_INTERNAL_OSC_HZ / (_PWM_RESOLUTION * freq_hz)) - 1
        prescale = max(3, min(255, prescale))  # datasheet-valid range
        old_mode = self._read_reg(_MODE1)
        self._write_reg(_MODE1, (old_mode & 0x7F) | _MODE1_SLEEP)  # sleep to change prescale
        self._write_reg(_PRESCALE, prescale)
        self._write_reg(_MODE1, old_mode)
        time.sleep(0.005)
        self._write_reg(_MODE1, old_mode | _MODE1_RESTART | _MODE1_AUTO_INCREMENT)
        self._write_reg(_MODE2, _MODE2_OUTDRV)

    def _write_channel_us(self, channel: int, pulse_us: float) -> None:
        period_us = 1_000_000.0 / self._freq
        if pulse_us <= 0:
            on_ticks, off_ticks = 0, 0  # fully off — no pulse train (torque disabled)
        else:
            on_ticks = 0
            off_ticks = max(
                1, min(_PWM_RESOLUTION - 1, round((pulse_us / period_us) * _PWM_RESOLUTION))
            )
        base = _LED0_ON_L + 4 * channel
        self._write_reg(base, on_ticks & 0xFF)
        self._write_reg(base + 1, (on_ticks >> 8) & 0xFF)
        self._write_reg(base + 2, off_ticks & 0xFF)
        self._write_reg(base + 3, (off_ticks >> 8) & 0xFF)

    def _angle_to_pulse_us(self, cal: ServoCalibration, angle_rad: float) -> float:
        span = cal.max_angle_rad - cal.min_angle_rad
        frac = 0.0 if span == 0 else (angle_rad - cal.min_angle_rad) / span
        frac = max(0.0, min(1.0, frac))
        if cal.invert:
            frac = 1.0 - frac
        return cal.min_pulse_us + frac * (cal.max_pulse_us - cal.min_pulse_us)

    # ── ServoDriver ──────────────────────────────────────────────────────────

    def read_all(self) -> list[ServoReading]:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        self._record_success()
        return [self._reading(sid) for sid in self._channels]

    def read_servo(self, servo_id: int) -> ServoReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if servo_id not in self._channels:
            raise DriverFault(f"Unknown servo {servo_id}", "INVALID_ID")
        self._record_success()
        return self._reading(servo_id)

    def _reading(self, servo_id: int) -> ServoReading:
        ch = self._channels[servo_id]
        _unmeasurable = float(
            "nan"
        )  # PWM RC servos have no feedback sensor -- see module docstring
        return ServoReading(
            servo_id=servo_id,
            position_rad=ch.commanded_rad,
            velocity_rads=_unmeasurable,
            load_percent=_unmeasurable,
            temperature_c=_unmeasurable,
            voltage_v=_unmeasurable,
            error_code=0,
            torque_enabled=ch.torque_enabled,
        )

    def write_command(self, cmd: ServoCommand) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        ch = self._channels.get(cmd.servo_id)
        if ch is None:
            raise DriverFault(f"Unknown servo {cmd.servo_id}", "INVALID_ID")
        if not ch.torque_enabled:
            return
        try:
            pulse_us = self._angle_to_pulse_us(ch.calibration, cmd.target_position_rad)
            self._write_channel_us(ch.calibration.channel, pulse_us)
            ch.commanded_rad = cmd.target_position_rad
            self._record_success()
        except Exception as exc:
            self._record_fault("I2C_WRITE_ERROR", str(exc))
            raise DriverFault(f"Write failed: {exc}", "I2C_WRITE_ERROR") from exc

    def write_commands(self, cmds: list[ServoCommand]) -> None:
        for cmd in cmds:
            self.write_command(cmd)

    def enable_torque(self, servo_id: int, enabled: bool) -> None:
        ch = self._channels.get(servo_id)
        if ch is None:
            return
        ch.torque_enabled = enabled
        if not enabled:
            self._write_channel_us(ch.calibration.channel, 0.0)
        else:
            pulse_us = self._angle_to_pulse_us(ch.calibration, ch.commanded_rad)
            self._write_channel_us(ch.calibration.channel, pulse_us)

    def enable_all_torque(self, enabled: bool) -> None:
        for sid in self._channels:
            self.enable_torque(sid, enabled)
