"""
Luxonis OAK-D Lite autofocus camera driver (Pi-2 hardware, see
config/distributed/pi_human_ai.yaml and
docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 3 -- this driver is the fix for
that HIGH-severity gap).

SDK dependency: depthai (pip install depthai). Import is lazy, mirroring
OrbbecDriver's pattern exactly: if the SDK is missing, `connect()` raises a
clear DriverFault("SDK_MISSING") instead of failing at import time, so the
rest of bonbon_hal still loads and camera_node can fall back to
UsbCameraDriver/MockCameraDriver (see camera_node.py's backend selection).

Streams:
  COLOR  requested width x height BGR8 @ requested fps (RGB camera, autofocus)
  DEPTH  requested width x height float32 metres (stereo depth pair)

Autofocus: OAK-D Lite's RGB sensor supports continuous autofocus via the
depthai CameraControl API -- enabled by default in _do_connect(), can be
toggled via set_autofocus() without a reconnect.
"""

from __future__ import annotations

import logging

import numpy as np

from bonbon_hal.base.driver_base import DriverFault

from .camera_driver import CameraDriver, ColorFrame, DepthFrame

logger = logging.getLogger(__name__)

_HAS_DEPTHAI = False
try:
    import depthai as dai  # type: ignore[import]

    _HAS_DEPTHAI = True
except ImportError:
    pass


# Approximate OAK-D Lite intrinsics when the device doesn't report
# calibration (e.g. during a dry pipeline build) -- RGB sensor HFOV ~69 deg.
_APPROX_HFOV_DEG = 69.0


class OAKDLiteDriver(CameraDriver):
    """Real Luxonis OAK-D Lite driver over USB, via depthai."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        depth_scale: float = 0.001,  # depthai reports depth in mm -> metres
        enable_autofocus: bool = True,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, driver_mode="real")
        self._depth_scale = depth_scale
        self._autofocus_enabled = enable_autofocus

        self._device = None
        self._q_rgb = None
        self._q_depth = None
        self._q_control = None
        self._calibration: dict | None = None

        if not _HAS_DEPTHAI:
            logger.warning(
                "depthai SDK not found — OAKDLiteDriver will fail to connect. "
                "Install with: pip install depthai"
            )

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_DEPTHAI:
            raise DriverFault("depthai SDK not installed", "SDK_MISSING", recoverable=False)

        try:
            pipeline = dai.Pipeline()

            cam_rgb = pipeline.create(dai.node.ColorCamera)
            cam_rgb.setPreviewSize(self.width, self.height)
            cam_rgb.setInterleaved(False)
            cam_rgb.setFps(self.fps)
            if self._autofocus_enabled:
                cam_rgb.initialControl.setAutoFocusMode(
                    dai.RawCameraControl.AutoFocusMode.CONTINUOUS_VIDEO
                )

            mono_left = pipeline.create(dai.node.MonoCamera)
            mono_right = pipeline.create(dai.node.MonoCamera)
            mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
            mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)

            stereo = pipeline.create(dai.node.StereoDepth)
            stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
            mono_left.out.link(stereo.left)
            mono_right.out.link(stereo.right)

            xout_rgb = pipeline.create(dai.node.XLinkOut)
            xout_rgb.setStreamName("rgb")
            cam_rgb.preview.link(xout_rgb.input)

            xout_depth = pipeline.create(dai.node.XLinkOut)
            xout_depth.setStreamName("depth")
            stereo.depth.link(xout_depth.input)

            xin_control = pipeline.create(dai.node.XLinkIn)
            xin_control.setStreamName("control")
            xin_control.out.link(cam_rgb.inputControl)

            self._device = dai.Device(pipeline)
            self._q_rgb = self._device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
            self._q_depth = self._device.getOutputQueue(name="depth", maxSize=4, blocking=False)
            self._q_control = self._device.getInputQueue(name="control")

            try:
                self._calibration = self._device.readCalibration().getCameraIntrinsics(
                    dai.CameraBoardSocket.RGB, self.width, self.height
                )
            except Exception as exc:  # noqa: BLE001 — calibration is optional, never fatal
                logger.warning("OAKDLiteDriver: could not read calibration: %s", exc)
                self._calibration = None

            logger.info(
                "OAKDLiteDriver: pipeline started @ %dx%d %dfps (autofocus=%s)",
                self.width,
                self.height,
                self.fps,
                self._autofocus_enabled,
            )
            return True

        except Exception as exc:
            raise DriverFault(
                f"depthai pipeline open failed: {exc}", "PIPELINE_OPEN_FAILED"
            ) from exc

    def _do_disconnect(self) -> None:
        try:
            if self._device is not None:
                self._device.close()
        except Exception as exc:
            logger.warning("OAKDLiteDriver disconnect error: %s", exc)
        finally:
            self._device = None
            self._q_rgb = None
            self._q_depth = None
            self._q_control = None

    # ── CameraDriver ──────────────────────────────────────────────────────────

    def read_frames(self) -> tuple[ColorFrame | None, DepthFrame | None]:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            color_frame = None
            depth_frame = None

            rgb_packet = self._q_rgb.tryGet() if self._q_rgb is not None else None
            if rgb_packet is not None:
                arr = rgb_packet.getCvFrame()  # BGR8, (H, W, 3)
                color_frame = ColorFrame(
                    width=self.width,
                    height=self.height,
                    data=np.ascontiguousarray(arr).tobytes(),
                    encoding="bgr8",
                )

            depth_packet = self._q_depth.tryGet() if self._q_depth is not None else None
            if depth_packet is not None:
                raw = depth_packet.getFrame().astype(np.float32)  # uint16 mm -> float32
                depth_arr = raw * self._depth_scale
                depth_arr[depth_arr == 0] = np.nan
                depth_frame = DepthFrame(
                    width=depth_arr.shape[1], height=depth_arr.shape[0], data=depth_arr
                )

            self._record_success()
            return color_frame, depth_frame

        except Exception as exc:
            self._record_fault("READ_ERROR", str(exc))
            raise DriverFault(f"Read failed: {exc}", "READ_ERROR") from exc

    def get_intrinsics(self) -> dict:
        if self._calibration:
            return {
                "width": self.width,
                "height": self.height,
                "fx": self._calibration[0][0],
                "fy": self._calibration[1][1],
                "cx": self._calibration[0][2],
                "cy": self._calibration[1][2],
            }
        # Honest fallback: synthesized from the documented HFOV, same
        # approximation strategy UsbCameraDriver uses when the device has
        # no calibration data -- never fabricated as if it were measured.
        import math

        fx = (self.width / 2.0) / math.tan(math.radians(_APPROX_HFOV_DEG / 2.0))
        return {
            "width": self.width,
            "height": self.height,
            "fx": fx,
            "fy": fx,
            "cx": self.width / 2.0,
            "cy": self.height / 2.0,
        }

    # ── OAK-D-specific: autofocus control ───────────────────────────────────────

    def set_autofocus(self, enabled: bool) -> None:
        """Toggle continuous autofocus without a reconnect. No-op (but
        honestly logged) if not connected -- never silently pretend success."""
        self._autofocus_enabled = enabled
        if self._q_control is None:
            logger.warning("OAKDLiteDriver.set_autofocus called while disconnected — ignored")
            return
        ctrl = dai.CameraControl()
        if enabled:
            ctrl.setAutoFocusMode(dai.RawCameraControl.AutoFocusMode.CONTINUOUS_VIDEO)
        else:
            ctrl.setAutoFocusMode(dai.RawCameraControl.AutoFocusMode.OFF)
        self._q_control.send(ctrl)
