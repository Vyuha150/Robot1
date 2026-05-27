"""
RPLIDAR S2 driver.

SDK dependency: rplidar-robotics  (pip install rplidar-robotics)
Hardware:       USB-to-serial at /dev/ttyUSB0 (typical), 115200 baud
"""

from __future__ import annotations

import logging
import math

from bonbon_hal.base.driver_base import DriverFault

from .lidar_driver import LidarDriver, LidarScan

logger = logging.getLogger(__name__)

try:
    from rplidar import RPLidar, RPLidarException  # type: ignore[import]

    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False
    logger.warning("rplidar-robotics not installed.  pip install rplidar-robotics")


class RplidarDriver(LidarDriver):
    """
    RPLIDAR S2 (and compatible A-series) driver.

    Parameters
    ----------
    port:
        Serial device, e.g. '/dev/ttyUSB0' or '/dev/ttyAMA0'
    baudrate:
        Default 115200 for S2; use 256000 for A3 models.
    scan_mode:
        None = device default (Sensitivity on S2).
        Override with 'Express', 'Boost', etc.
    """

    RANGE_MIN_M = 0.15
    RANGE_MAX_M = 30.0

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        scan_mode: str = None,
        timeout: float = 3.0,
    ) -> None:
        super().__init__(driver_mode="real", connect_timeout_sec=timeout)
        self._port = port
        self._baudrate = baudrate
        self._scan_mode = scan_mode
        self._lidar = None
        self._iterator = None

    def _do_connect(self) -> bool:
        if not _HAS_SDK:
            raise DriverFault("rplidar SDK not installed", "SDK_MISSING", recoverable=False)
        try:
            self._lidar = RPLidar(self._port, self._baudrate, timeout=3)
            info = self._lidar.get_info()
            logger.info("RPLIDAR info: %s", info)
            health = self._lidar.get_health()
            logger.info("RPLIDAR health: %s", health)
            if health[0] == "Error":
                raise DriverFault(f"LIDAR health error: {health}", "HEALTH_ERROR")
            self._lidar.start_motor()
            self._iterator = self._lidar.iter_scans(
                scan_type=self._scan_mode or "normal",
                min_len=5,
                max_buf_meas=3000,
            )
            return True
        except RPLidarException as exc:
            raise DriverFault(str(exc), "RPLIDAR_EXCEPTION") from exc
        except Exception as exc:
            raise DriverFault(str(exc), "CONNECT_ERROR") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._lidar:
                self._lidar.stop()
                self._lidar.stop_motor()
                self._lidar.disconnect()
        except Exception as exc:
            logger.warning("RPLIDAR disconnect error: %s", exc)
        finally:
            self._lidar = None
            self._iterator = None

    def read_scan(self) -> LidarScan:
        if not self.is_connected or self._iterator is None:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            # One scan = list of (quality, angle_deg, distance_mm)
            measurements = next(self._iterator)

            # Sort by angle
            measurements.sort(key=lambda m: m[1])

            # Build uniform 360-ray representation
            ranges: list[float] = [math.inf] * 360
            intensities: list[float] = [0.0] * 360

            for quality, angle_deg, dist_mm in measurements:
                idx = int(angle_deg) % 360
                dist_m = dist_mm / 1000.0
                if dist_m < self.RANGE_MIN_M or dist_m > self.RANGE_MAX_M:
                    continue
                if ranges[idx] == math.inf or dist_m < ranges[idx]:
                    ranges[idx] = dist_m
                    intensities[idx] = float(quality)

            self._record_success()
            return LidarScan(
                ranges=ranges,
                intensities=intensities,
                angle_min_rad=-math.pi,
                angle_max_rad=math.pi,
                range_min_m=self.RANGE_MIN_M,
                range_max_m=self.RANGE_MAX_M,
            )

        except StopIteration:
            self._record_fault("SCAN_ENDED", "Scan iterator exhausted")
            raise DriverFault("Scan iterator ended", "SCAN_ENDED") from None
        except Exception as exc:
            self._record_fault("READ_ERROR", str(exc))
            raise DriverFault(str(exc), "READ_ERROR") from exc
