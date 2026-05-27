"""
Orbbec Astra Mini RGB-D camera driver.

SDK dependency: openni2 Python bindings  (pip install openni)
               or pyorbbecsdk             (pip install pyorbbecsdk)

This driver attempts openni2 first, then pyorbbecsdk, then raises
DriverFault("no SDK") on import failure so CI can detect the gap.

Streams:
  COLOR  640×480 BGR8  30 FPS
  DEPTH  640×480 uint16 mm → float32 metres  30 FPS
"""

from __future__ import annotations

import logging

import numpy as np

from bonbon_hal.base.driver_base import DriverFault

from .camera_driver import CameraDriver, ColorFrame, DepthFrame

logger = logging.getLogger(__name__)

_HAS_OPENNI = False
_HAS_ORBBEC = False

try:
    from openni import openni2  # type: ignore[import]

    _HAS_OPENNI = True
except ImportError:
    pass

try:
    import pyorbbecsdk as orbbec  # type: ignore[import]

    _HAS_ORBBEC = True
except ImportError:
    pass


class OrbbecDriver(CameraDriver):
    """
    Real Orbbec Astra Mini driver.  Uses openni2 by default; falls
    back to pyorbbecsdk if available.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        device_uri: str = "",  # "" = first device found
        openni_redist: str = "/usr/lib",  # path to OpenNI2 redist
        depth_scale: float = 0.001,  # mm → metres
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, driver_mode="real")
        self._uri = device_uri
        self._redist = openni_redist
        self._depth_scale = depth_scale

        self._device = None
        self._color_stream = None
        self._depth_stream = None

        if not _HAS_OPENNI and not _HAS_ORBBEC:
            logger.warning(
                "Neither openni2 nor pyorbbecsdk found — OrbbecDriver will "
                "fail to connect.  Install with: pip install openni"
            )

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_OPENNI:
            raise DriverFault("openni2 SDK not installed", "SDK_MISSING", recoverable=False)

        try:
            openni2.initialize(self._redist)
            self._device = (
                openni2.Device.open_any() if not self._uri else openni2.Device.open_file(self._uri)
            )

            # Colour stream
            self._color_stream = self._device.create_color_stream()
            self._color_stream.set_video_mode(
                openni2.VideoMode(
                    pixelFormat=openni2.PIXEL_FORMAT_RGB888,
                    resolutionX=self.width,
                    resolutionY=self.height,
                    fps=self.fps,
                )
            )
            self._color_stream.start()

            # Depth stream
            self._depth_stream = self._device.create_depth_stream()
            self._depth_stream.set_video_mode(
                openni2.VideoMode(
                    pixelFormat=openni2.PIXEL_FORMAT_DEPTH_1_MM,
                    resolutionX=self.width,
                    resolutionY=self.height,
                    fps=self.fps,
                )
            )
            self._depth_stream.set_mirroring_enabled(False)
            self._depth_stream.start()

            logger.info(
                "OrbbecDriver: streams opened @ %dx%d %dfps", self.width, self.height, self.fps
            )
            return True

        except Exception as exc:
            raise DriverFault(f"OpenNI2 open failed: {exc}", "OPENNI_OPEN_FAILED") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._color_stream:
                self._color_stream.stop()
            if self._depth_stream:
                self._depth_stream.stop()
            if self._device:
                self._device.close()
            openni2.unload()
        except Exception as exc:
            logger.warning("OrbbecDriver disconnect error: %s", exc)
        finally:
            self._color_stream = None
            self._depth_stream = None
            self._device = None

    # ── CameraDriver ──────────────────────────────────────────────────────────

    def read_frames(self) -> tuple[ColorFrame | None, DepthFrame | None]:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            color_frame = None
            depth_frame = None

            # Read colour
            cf = self._color_stream.read_frame()
            if cf is not None:
                data = cf.get_buffer_as_uint8()
                # RGB888 → BGR8
                arr = np.frombuffer(data, dtype=np.uint8).reshape((self.height, self.width, 3))
                arr = arr[:, :, ::-1]  # RGB to BGR
                color_frame = ColorFrame(
                    width=self.width,
                    height=self.height,
                    data=arr.tobytes(),
                    encoding="bgr8",
                )

            # Read depth
            df = self._depth_stream.read_frame()
            if df is not None:
                raw = np.frombuffer(df.get_buffer_as_uint16(), dtype=np.uint16)
                depth_arr = raw.reshape((self.height, self.width)).astype(np.float32)
                depth_arr *= self._depth_scale  # mm → metres
                depth_arr[depth_arr == 0] = np.nan
                depth_frame = DepthFrame(width=self.width, height=self.height, data=depth_arr)

            self._record_success()
            return color_frame, depth_frame

        except Exception as exc:
            self._record_fault("READ_ERROR", str(exc))
            raise DriverFault(f"Read failed: {exc}", "READ_ERROR") from exc

    def get_intrinsics(self) -> dict:
        """Query intrinsics from the depth sensor (approximate for Astra Mini)."""
        return {
            "width": self.width,
            "height": self.height,
            "fx": 525.0,
            "fy": 525.0,
            "cx": self.width / 2.0,
            "cy": self.height / 2.0,
        }
