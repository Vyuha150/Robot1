"""
Abstract camera driver — Orbbec Astra Mini RGB-D.

Produces:
  ColorFrame  640×480 BGR8 @ 30 FPS
  DepthFrame  640×480 float32 metres @ 30 FPS
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

import numpy as np

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class ColorFrame:
    width: int
    height: int
    data: bytes  # raw BGR8 bytes
    encoding: str = "bgr8"
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class DepthFrame:
    width: int
    height: int
    data: np.ndarray  # float32 (H,W), metres; nan = invalid
    min_depth_m: float = 0.3
    max_depth_m: float = 8.0
    timestamp: float = field(default_factory=time.monotonic)


class CameraDriver(DriverBase):
    """
    Abstract camera driver.  Subclasses implement:
      _do_connect / _do_disconnect / read_frames()
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30, **kwargs) -> None:
        super().__init__("camera", **kwargs)
        self.width = width
        self.height = height
        self.fps = fps

    @abstractmethod
    def read_frames(self) -> tuple[ColorFrame | None, DepthFrame | None]:
        """
        Return the latest (color, depth) frame pair.
        Either element may be None if that stream is unavailable.
        Raises DriverFault on hardware error.
        """

    @abstractmethod
    def get_intrinsics(self) -> dict:
        """Return camera intrinsic matrix as {'fx','fy','cx','cy','width','height'}."""
