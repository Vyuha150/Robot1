"""
INA226 high-side power monitor driver (I2C).

Measures:  bus voltage, shunt voltage → current → power
Wiring:    Shunt resistor (10 mΩ) in series with battery positive rail
           I2C: SDA→pin3  SCL→pin5  (Jetson bus 1)
Address:   0x40 default (A0=GND, A1=GND)

SDK dependency: smbus2  (pip install smbus2)
"""

from __future__ import annotations

import logging

from bonbon_hal.base.driver_base import DriverFault

from .battery_driver import BatteryDriver, BatteryReading, voltage_to_percent

logger = logging.getLogger(__name__)

try:
    import smbus2  # type: ignore[import]

    _HAS_SMBUS = True
except ImportError:
    _HAS_SMBUS = False

# INA226 registers
_REG_CONFIG = 0x00
_REG_SHUNT = 0x01  # shunt voltage (2.5 µV/LSB, signed)
_REG_BUS = 0x02  # bus voltage   (1.25 mV/LSB)
_REG_POWER = 0x03  # power         (25 mW/LSB × calibration)
_REG_CURRENT = 0x04  # current       (calibration dependent)
_REG_CALIB = 0x05
_REG_MASK_EN = 0x06
_REG_ALERT = 0x07
_REG_MFRID = 0xFE  # 0x5449
_REG_DIEID = 0xFF  # 0x2260

# Default config: avg=16, vbus_ct=1.1ms, vsh_ct=1.1ms, continuous
_DEFAULT_CONFIG = 0x4527
_SHUNT_LSB_UV = 2.5e-6  # 2.5 µV per LSB
_BUS_LSB_V = 1.25e-3  # 1.25 mV per LSB
_CURRENT_LSB_A = 0.001  # 1 mA per LSB (for 10 mΩ shunt, Rshunt=0.01)


class Ina226Driver(BatteryDriver):

    def __init__(
        self,
        bus: int = 1,
        address: int = 0x40,
        shunt_ohm: float = 0.01,  # 10 mΩ shunt resistor
        max_a: float = 20.0,  # max expected current
        capacity_ah: float = 40.0,  # battery capacity
    ) -> None:
        super().__init__(driver_mode="real")
        self._bus_num = bus
        self._addr = address
        self._shunt = shunt_ohm
        self._max_a = max_a
        self._capacity_ah = capacity_ah
        self._bus_obj = None
        self._current_lsb = 0.0
        self._power_lsb = 0.0

    def _do_connect(self) -> bool:
        if not _HAS_SMBUS:
            raise DriverFault("smbus2 not installed", "SDK_MISSING", recoverable=False)
        try:
            self._bus_obj = smbus2.SMBus(self._bus_num)
            # Verify manufacturer ID
            mfr = self._read_reg(_REG_MFRID)
            if mfr != 0x5449:
                raise DriverFault(f"INA226 not found (MFR=0x{mfr:04x})", "WRONG_DEVICE")
            # Calibrate
            self._current_lsb = self._max_a / 32768.0
            self._power_lsb = self._current_lsb * 25.0
            cal = int(0.00512 / (self._current_lsb * self._shunt))
            self._write_reg(_REG_CALIB, cal)
            self._write_reg(_REG_CONFIG, _DEFAULT_CONFIG)
            logger.info(
                "INA226 connected on bus %d addr 0x%02x, current_lsb=%.6f A",
                self._bus_num,
                self._addr,
                self._current_lsb,
            )
            return True
        except DriverFault:
            raise
        except Exception as exc:
            raise DriverFault(str(exc), "I2C_CONNECT_FAILED") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._bus_obj:
                self._bus_obj.close()
        except Exception:
            pass
        self._bus_obj = None

    def read(self) -> BatteryReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            raw_bus = self._read_reg(_REG_BUS)
            self._read_signed(_REG_SHUNT)
            raw_curr = self._read_signed(_REG_CURRENT)
            raw_pwr = self._read_reg(_REG_POWER)

            voltage_v = raw_bus * _BUS_LSB_V
            current_a = raw_curr * self._current_lsb
            power_w = raw_pwr * self._power_lsb
            percent = voltage_to_percent(voltage_v)
            is_charging = current_a > 0.1

            self._record_success()
            return BatteryReading(
                voltage_v=voltage_v,
                current_a=current_a,
                power_w=power_w,
                percent=percent,
                is_charging=is_charging,
            )
        except Exception as exc:
            self._record_fault("I2C_READ_ERROR", str(exc))
            raise DriverFault(str(exc), "I2C_READ_ERROR") from exc

    def _read_reg(self, reg: int) -> int:
        data = self._bus_obj.read_i2c_block_data(self._addr, reg, 2)
        return (data[0] << 8) | data[1]

    def _read_signed(self, reg: int) -> int:
        val = self._read_reg(reg)
        return val - 65536 if val > 32767 else val

    def _write_reg(self, reg: int, value: int) -> None:
        self._bus_obj.write_i2c_block_data(self._addr, reg, [(value >> 8) & 0xFF, value & 0xFF])
