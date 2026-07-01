"""Tests for OAKDLiteDriver.

depthai is not installed in this dev environment, so this suite exercises
the exact same honest-gap path OrbbecDriver already has real test coverage
for: connect() must raise a clear DriverFault, never silently pretend
success. get_intrinsics()'s no-calibration fallback needs no SDK at all,
so it's tested directly against real (not mocked) behavior.
"""

from __future__ import annotations

import math

import pytest
from bonbon_hal.base.driver_base import DriverFault, DriverStatus
from bonbon_hal.drivers.camera import OAKDLiteDriver
from bonbon_hal.drivers.camera.oakd_lite_driver import _HAS_DEPTHAI


class TestOAKDLiteDriverNoSDK:
    """These assertions are REAL, not mocked: depthai genuinely is not
    installed in this sandbox, so this is the actual behavior a developer
    machine or a Pi without the SDK installed would see."""

    def test_sdk_not_installed_in_this_environment(self):
        # Documents the precondition the rest of this class relies on --
        # if depthai ever gets installed here, these tests should be
        # revisited rather than silently keep "testing" a path that no
        # longer executes.
        assert _HAS_DEPTHAI is False

    def test_connect_fails_honestly_when_sdk_missing(self):
        # DriverBase.connect() catches _do_connect()'s DriverFault and
        # returns False rather than propagating -- verified against real
        # driver_base.py behavior, not assumed. See test_camera_driver.py's
        # test_start_disconnected for the same pattern on MockCameraDriver.
        drv = OAKDLiteDriver(width=64, height=48)
        ok = drv.connect()
        assert ok is False

    def test_status_after_failed_connect_is_not_connected(self):
        drv = OAKDLiteDriver(width=64, height=48)
        drv.connect()
        assert drv.is_connected is False
        assert drv.status != DriverStatus.CONNECTED

    def test_read_without_connect_raises_not_connected(self):
        drv = OAKDLiteDriver(width=64, height=48)
        with pytest.raises(DriverFault) as exc:
            drv.read_frames()
        assert exc.value.error_code == "NOT_CONNECTED"


class TestOAKDLiteDriverIntrinsicsFallback:
    """get_intrinsics() with no calibration data needs no hardware/SDK --
    exercised directly against the real (uninstantiated-pipeline) driver."""

    def test_fallback_intrinsics_shape(self):
        drv = OAKDLiteDriver(width=640, height=480)
        intr = drv.get_intrinsics()
        assert intr["width"] == 640
        assert intr["height"] == 480
        assert intr["fx"] > 0
        assert intr["fy"] == intr["fx"]
        assert intr["cx"] == 320.0
        assert intr["cy"] == 240.0

    def test_fallback_intrinsics_match_documented_hfov(self):
        drv = OAKDLiteDriver(width=640, height=480)
        intr = drv.get_intrinsics()
        # fx = (width/2) / tan(hfov/2) -- reverse the formula to confirm
        # the driver used the documented ~69 deg HFOV, not an arbitrary value.
        implied_hfov_deg = 2 * math.degrees(math.atan((640 / 2.0) / intr["fx"]))
        assert 68.0 < implied_hfov_deg < 70.0

    def test_set_autofocus_while_disconnected_does_not_raise(self):
        drv = OAKDLiteDriver(width=64, height=48)
        drv.set_autofocus(False)  # must log+no-op, never crash
        drv.set_autofocus(True)


if __name__ == "__main__":
    pytest.main([__file__])
