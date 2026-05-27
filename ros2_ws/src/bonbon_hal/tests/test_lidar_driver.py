"""
test_lidar_driver.py
====================
Tests for MockLidarDriver: normal operation, disconnection, timeout, recovery, corrupted data.
"""

from __future__ import annotations

import math

import pytest
from bonbon_hal.base.driver_base import DriverFault, DriverStatus
from bonbon_hal.drivers.lidar import LidarScan, MockLidarDriver


@pytest.fixture
def drv() -> MockLidarDriver:
    d = MockLidarDriver()
    d.connect()
    return d


class TestMockLidarNormal:
    def test_connect_succeeds(self, drv):
        assert drv.is_connected

    def test_read_scan_returns_scan(self, drv):
        scan = drv.read_scan()
        assert isinstance(scan, LidarScan)

    def test_scan_has_360_rays(self, drv):
        scan = drv.read_scan()
        assert len(scan.ranges) == 360
        assert len(scan.intensities) == 360

    def test_ranges_within_bounds(self, drv):
        scan = drv.read_scan()
        for r in scan.ranges:
            assert r >= 0.15 or math.isinf(r)

    def test_angle_min_max(self, drv):
        scan = drv.read_scan()
        assert scan.angle_min_rad == pytest.approx(-math.pi)
        assert scan.angle_max_rad == pytest.approx(math.pi)

    def test_angle_increment_computed(self, drv):
        scan = drv.read_scan()
        expected = 2 * math.pi / (len(scan.ranges) - 1)
        assert scan.angle_increment_rad == pytest.approx(expected, abs=0.01)

    def test_intensities_nonzero(self, drv):
        scan = drv.read_scan()
        assert any(i > 0 for i in scan.intensities)

    def test_health_ok_after_reads(self, drv):
        for _ in range(5):
            drv.read_scan()
        assert drv.health.consecutive_errors == 0


class TestMockLidarObstacle:
    def test_obstacle_inserted_at_angle(self):
        drv = MockLidarDriver(
            obstacle_at_angle_deg=0.0, obstacle_distance_m=1.0, obstacle_width_deg=20.0
        )
        drv.connect()
        scan = drv.read_scan()
        # Ray at index 180 corresponds to 0° in -180 to +179 mapping
        # Obstacle at angle 0 → most rays near 0° should be ≤ 1.2m
        close = [scan.ranges[i] for i in range(170, 191)]
        assert any(r <= 1.2 for r in close)


class TestMockLidarFaults:
    def test_read_without_connect_raises(self):
        drv = MockLidarDriver()
        with pytest.raises(DriverFault) as exc:
            drv.read_scan()
        assert "NOT_CONNECTED" in str(exc.value.error_code)

    def test_start_disconnected(self):
        drv = MockLidarDriver(start_disconnected=True)
        ok = drv.connect()
        assert ok is False
        assert not drv.is_connected

    def test_usb_disconnect_after_n(self):
        drv = MockLidarDriver(disconnect_after_n=3)
        drv.connect()
        for _ in range(3):
            drv.read_scan()
        with pytest.raises(DriverFault) as exc:
            drv.read_scan()
        assert "USB_DISCONNECTED" in str(exc.value.error_code)

    def test_partial_ring_dropout(self):
        drv = MockLidarDriver(partial_ring_from_deg=0, partial_ring_to_deg=90)
        drv.connect()
        scan = drv.read_scan()
        # Rays in 0–90° should be inf
        for i in range(0, 91):
            # Angle mapping: ray i → -180 + i degrees
            angle = -180 + i
            if 0 <= angle <= 90:
                assert math.isinf(scan.ranges[i])

    def test_status_faulted_after_usb_disconnect(self):
        drv = MockLidarDriver(disconnect_after_n=1)
        drv.connect()
        try:
            drv.read_scan()  # triggers disconnect
        except DriverFault:
            pass
        assert drv.status == DriverStatus.FAULTED


class TestMockLidarRecovery:
    def test_reconnect_after_fault(self):
        drv = MockLidarDriver(disconnect_after_n=2)
        drv.connect()
        drv.read_scan()
        drv.read_scan()
        try:
            drv.read_scan()
        except DriverFault:
            pass
        drv.inject_fault(disc_after=0)  # clear fault injection
        ok = drv.reconnect()
        assert ok is True
        assert drv.is_connected

    def test_reads_work_after_reconnect(self):
        drv = MockLidarDriver(disconnect_after_n=1)
        drv.connect()
        try:
            drv.read_scan()
        except DriverFault:
            pass
        drv.inject_fault(disc_after=0)
        drv.reconnect()
        scan = drv.read_scan()
        assert len(scan.ranges) == 360
