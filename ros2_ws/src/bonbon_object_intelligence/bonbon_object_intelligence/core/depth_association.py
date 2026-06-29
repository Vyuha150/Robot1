"""Derives a 3D position from a 2D detection + depth, using the same pinhole
intrinsics convention already established by bonbon_hal.UsbCameraDriver
(fx = (width/2) / tan(hfov/2)) — real, documented camera geometry, not
invented math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CameraIntrinsics:
    width_px: int
    height_px: int
    hfov_deg: float = 60.0

    @property
    def fx(self) -> float:
        return (self.width_px / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    @property
    def fy(self) -> float:
        return self.fx  # square pixels assumed, consistent with UsbCameraDriver


def pixel_to_position_3d(
    bbox_center_x_px: float,
    bbox_center_y_px: float,
    depth_m: float,
    intrinsics: CameraIntrinsics,
) -> tuple[float, float, float]:
    """Returns (x, y, z) in the camera-forward robot frame: x=forward(depth),
    y=left/right offset, z=up/down offset. NaN depth propagates as NaN
    position (caller must check, never silently treated as 0)."""
    if depth_m != depth_m:  # NaN check without importing math.isnan for clarity
        return (float("nan"), float("nan"), float("nan"))

    cx = intrinsics.width_px / 2.0
    cy = intrinsics.height_px / 2.0
    y = -(bbox_center_x_px - cx) * depth_m / intrinsics.fx
    z = -(bbox_center_y_px - cy) * depth_m / intrinsics.fy
    return (depth_m, y, z)
