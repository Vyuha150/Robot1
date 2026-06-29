"""Tests for pixel_to_position_3d / CameraIntrinsics."""

from __future__ import annotations

import math

from bonbon_object_intelligence.core.depth_association import (
    CameraIntrinsics,
    pixel_to_position_3d,
)


class TestCameraIntrinsics:
    def test_fx_matches_usb_camera_driver_formula(self):
        intr = CameraIntrinsics(width_px=640, height_px=480, hfov_deg=60.0)
        expected = (640 / 2.0) / math.tan(math.radians(60.0) / 2.0)
        assert abs(intr.fx - expected) < 1e-6

    def test_fy_equals_fx_square_pixels(self):
        intr = CameraIntrinsics(width_px=640, height_px=480, hfov_deg=60.0)
        assert intr.fx == intr.fy


class TestPixelToPosition3D:
    def test_centered_object_has_zero_lateral_offset(self):
        intr = CameraIntrinsics(640, 480, 60.0)
        x, y, z = pixel_to_position_3d(320, 240, depth_m=2.0, intrinsics=intr)
        assert x == 2.0
        assert abs(y) < 1e-6
        assert abs(z) < 1e-6

    def test_object_left_of_center_has_positive_y(self):
        intr = CameraIntrinsics(640, 480, 60.0)
        x, y, z = pixel_to_position_3d(100, 240, depth_m=2.0, intrinsics=intr)
        assert y > 0  # left of center -> positive y per this module's convention

    def test_nan_depth_propagates_as_nan_not_zero(self):
        intr = CameraIntrinsics(640, 480, 60.0)
        x, y, z = pixel_to_position_3d(320, 240, depth_m=float("nan"), intrinsics=intr)
        assert math.isnan(x)
        assert math.isnan(y)
        assert math.isnan(z)
