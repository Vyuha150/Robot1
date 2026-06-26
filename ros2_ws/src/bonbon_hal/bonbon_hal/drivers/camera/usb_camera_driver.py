"""
Generic USB / V4L2 camera driver (OpenCV-backed).

For Raspberry Pi + any standard USB webcam (or the Pi CSI camera exposed through
V4L2). Produces a ColorFrame (BGR8); no depth stream (returns None for depth),
so the perception stack falls back to monocular distance estimation.

OpenCV is an optional import: if it is missing the driver raises a clear
``DriverFault`` at connect time rather than at import, so the rest of the HAL
still loads and the node can fall back to the mock driver.
"""

from __future__ import annotations

import logging
import math
import time

from bonbon_hal.base.driver_base import DriverFault

from .camera_driver import CameraDriver, ColorFrame, DepthFrame  # noqa: F401

logger = logging.getLogger(__name__)

try:
    import cv2  # type: ignore[import]
    _HAS_CV2 = True
except Exception:  # noqa: BLE001
    _HAS_CV2 = False


class UsbCameraDriver(CameraDriver):
    """USB / V4L2 webcam via OpenCV ``VideoCapture``.

    Args:
        device: V4L2 index (``0`` → /dev/video0) or a device path / URL string.
        width, height, fps: requested capture format (the device picks the
            nearest it supports).
        hfov_deg: horizontal field of view, used to synthesise intrinsics when
            the camera does not report them.
        fourcc: optional pixel format hint (e.g. ``"MJPG"`` for higher USB FPS).
    """

    def __init__(
        self,
        device: int | str = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        hfov_deg: float = 60.0,
        fourcc: str = "MJPG",
        **kwargs,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, driver_mode="real", **kwargs)
        self._device = device
        self._hfov_deg = hfov_deg
        self._fourcc = fourcc
        self._cap = None
        self._consecutive_failures = 0

    # ── DriverBase ────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_CV2:
            raise DriverFault(
                "OpenCV (cv2) not installed — install with: pip install opencv-python-headless",
                "SDK_MISSING", recoverable=False,
            )
        # Prefer the V4L2 backend on Linux (Raspberry Pi); fall back to ANY.
        backend = getattr(cv2, "CAP_V4L2", 0)
        cap = cv2.VideoCapture(self._device, backend)
        if not cap or not cap.isOpened():
            cap = cv2.VideoCapture(self._device)  # any available backend
        if not cap or not cap.isOpened():
            raise DriverFault(
                f"could not open camera device {self._device!r}",
                "DEVICE_OPEN_FAILED", recoverable=True,
            )
        try:
            if self._fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # lowest latency — always newest frame
        except Exception as exc:  # noqa: BLE001
            logger.warning("camera property set failed (non-fatal): %s", exc)

        # Read the actual negotiated format.
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.width)
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        if actual_fps and actual_fps > 0:
            self.fps = int(actual_fps)

        # Warm-up read to confirm frames actually flow.
        ok, _ = cap.read()
        if not ok:
            cap.release()
            raise DriverFault("camera opened but returned no frame", "NO_FRAME", recoverable=True)

        self._cap = cap
        self._consecutive_failures = 0
        logger.info(
            "USB camera connected: device=%s %dx%d @ %d fps", self._device,
            self.width, self.height, self.fps,
        )
        return True

    def _do_disconnect(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    # ── CameraDriver ──────────────────────────────────────────────────────────

    def read_frames(self) -> tuple[ColorFrame | None, DepthFrame | None]:
        if self._cap is None:
            raise DriverFault("camera not connected", "NOT_CONNECTED", recoverable=True)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 5:
                raise DriverFault(
                    "camera returned no frame 5x — likely disconnected",
                    "FRAME_READ_FAILED", recoverable=True,
                )
            return (None, None)
        self._consecutive_failures = 0
        h, w = frame.shape[0], frame.shape[1]
        color = ColorFrame(
            width=w, height=h, data=frame.tobytes(), encoding="bgr8",
            timestamp=time.monotonic(),
        )
        return (color, None)  # monocular USB cam → no depth

    def get_intrinsics(self) -> dict:
        # Synthesise a pinhole model from the horizontal FOV when the device
        # does not provide a factory calibration.
        fx = (self.width / 2.0) / math.tan(math.radians(self._hfov_deg) / 2.0)
        fy = fx  # assume square pixels
        return {
            "fx": fx, "fy": fy,
            "cx": self.width / 2.0, "cy": self.height / 2.0,
            "width": self.width, "height": self.height,
        }
