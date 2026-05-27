"""
MPU-6050 / MPU-9250 IMU driver via I2C (smbus2).

Wiring (Jetson Orin Nano):
  VCC → 3.3V   GND → GND
  SDA → pin 3  SCL → pin 5   (I2C bus 1 by default)
  AD0 → GND → I2C address 0x68

SDK dependency: smbus2  (pip install smbus2)
"""

from __future__ import annotations

import logging
import struct
import time

from bonbon_hal.base.driver_base import DriverFault

from .imu_driver import ImuDriver, ImuReading

logger = logging.getLogger(__name__)

try:
    import smbus2  # type: ignore[import]

    _HAS_SMBUS = True
except ImportError:
    _HAS_SMBUS = False
    logger.warning("smbus2 not installed. pip install smbus2")

# MPU-6050 register map
_PWR_MGMT_1 = 0x6B
_SMPLRT_DIV = 0x19
_CONFIG_REG = 0x1A
_GYRO_CONFIG = 0x1B
_ACCEL_CONFIG = 0x1C
_ACCEL_XOUT_H = 0x3B  # 14 bytes: AXYZ + TEMP + GXYZ
_WHO_AM_I = 0x75

# Scale factors (±2g, ±250°/s defaults)
_ACCEL_SCALE = 16384.0  # LSB/g
_GYRO_SCALE = 131.0  # LSB / (°/s)
_TEMP_OFFSET = 36.53
_TEMP_SCALE = 340.0
_G = 9.80665  # m/s²
_DEG2RAD = 0.017453292519943295


class Mpu6050Driver(ImuDriver):

    def __init__(
        self,
        bus: int = 1,
        address: int = 0x68,
        sample_rate_hz: int = 100,
        accel_range_g: int = 2,  # 2, 4, 8, 16
        gyro_range_dps: int = 250,  # 250, 500, 1000, 2000
    ) -> None:
        super().__init__(driver_mode="real")
        self._bus_num = bus
        self._addr = address
        self._sample_rate = sample_rate_hz
        self._accel_range = accel_range_g
        self._gyro_range = gyro_range_dps
        self._bus = None
        self._accel_scale = 16384.0
        self._gyro_scale = 131.0
        # Calibration offsets
        self._ax_off = self._ay_off = self._az_off = 0.0
        self._gx_off = self._gy_off = self._gz_off = 0.0

    def _do_connect(self) -> bool:
        if not _HAS_SMBUS:
            raise DriverFault("smbus2 not installed", "SDK_MISSING", recoverable=False)
        try:
            self._bus = smbus2.SMBus(self._bus_num)
            who = self._bus.read_byte_data(self._addr, _WHO_AM_I)
            if who not in (0x68, 0x70, 0x71, 0x73):
                raise DriverFault(f"Unexpected WHO_AM_I: 0x{who:02x}", "WRONG_DEVICE")
            # Wake up
            self._bus.write_byte_data(self._addr, _PWR_MGMT_1, 0x00)
            time.sleep(0.1)
            # Configure sample rate
            div = max(0, 1000 // self._sample_rate - 1)
            self._bus.write_byte_data(self._addr, _SMPLRT_DIV, div)
            # Configure ranges
            range_map_a = {2: 0x00, 4: 0x08, 8: 0x10, 16: 0x18}
            range_map_g = {250: 0x00, 500: 0x08, 1000: 0x10, 2000: 0x18}
            self._bus.write_byte_data(
                self._addr, _ACCEL_CONFIG, range_map_a.get(self._accel_range, 0x00)
            )
            self._bus.write_byte_data(
                self._addr, _GYRO_CONFIG, range_map_g.get(self._gyro_range, 0x00)
            )
            scale_a = {2: 16384.0, 4: 8192.0, 8: 4096.0, 16: 2048.0}
            scale_g = {250: 131.0, 500: 65.5, 1000: 32.8, 2000: 16.4}
            self._accel_scale = scale_a[self._accel_range]
            self._gyro_scale = scale_g[self._gyro_range]
            logger.info("MPU-6050 connected on bus %d, addr 0x%02x", self._bus_num, self._addr)
            return True
        except Exception as exc:
            raise DriverFault(str(exc), "I2C_CONNECT_FAILED") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._bus:
                self._bus.close()
        except Exception:
            pass
        finally:
            self._bus = None

    def read(self) -> ImuReading:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            raw = self._bus.read_i2c_block_data(self._addr, _ACCEL_XOUT_H, 14)
            ax, ay, az, temp_raw, gx, gy, gz = struct.unpack(">7h", bytes(raw))

            ax_ms2 = (ax / self._accel_scale) * _G - self._ax_off
            ay_ms2 = (ay / self._accel_scale) * _G - self._ay_off
            az_ms2 = (az / self._accel_scale) * _G - self._az_off
            gx_rs = (gx / self._gyro_scale) * _DEG2RAD - self._gx_off
            gy_rs = (gy / self._gyro_scale) * _DEG2RAD - self._gy_off
            gz_rs = (gz / self._gyro_scale) * _DEG2RAD - self._gz_off
            temp_c = temp_raw / _TEMP_SCALE + _TEMP_OFFSET

            self._record_success()
            return ImuReading(
                accel_x=ax_ms2,
                accel_y=ay_ms2,
                accel_z=az_ms2,
                gyro_x=gx_rs,
                gyro_y=gy_rs,
                gyro_z=gz_rs,
                temperature_c=temp_c,
            )
        except Exception as exc:
            self._record_fault("I2C_READ_ERROR", str(exc))
            raise DriverFault(str(exc), "I2C_READ_ERROR") from exc

    def calibrate(self) -> None:
        """Collect 200 samples at rest and compute offsets."""
        logger.info("MPU-6050: starting calibration (keep robot stationary)…")
        ax_s = ay_s = az_s = gx_s = gy_s = gz_s = 0.0
        n = 200
        for _ in range(n):
            r = self.read()
            ax_s += r.accel_x
            ay_s += r.accel_y
            az_s += r.accel_z
            gx_s += r.gyro_x
            gy_s += r.gyro_y
            gz_s += r.gyro_z
            time.sleep(0.005)
        self._ax_off = ax_s / n
        self._ay_off = ay_s / n
        self._az_off = az_s / n - _G  # z should be +g
        self._gx_off = gx_s / n
        self._gy_off = gy_s / n
        self._gz_off = gz_s / n
        logger.info(
            "MPU-6050: calibration complete. offsets: a=(%.4f,%.4f,%.4f) g=(%.4f,%.4f,%.4f)",
            self._ax_off,
            self._ay_off,
            self._az_off,
            self._gx_off,
            self._gy_off,
            self._gz_off,
        )
