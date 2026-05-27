"""
Mock camera driver — generates synthetic frames for simulation / CI.

Fault injection (set via inject_fault() or constructor kwargs):
  disconnect_after_n_reads   – simulate USB pull after N reads
  corrupt_every_n_frames     – return a frame with random pixel corruption
  depth_noise_sigma          – add Gaussian noise to depth (metres)
  simulate_latency_sec       – artificial sleep per read
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np

from bonbon_hal.base.driver_base import DriverFault

from .camera_driver import CameraDriver, ColorFrame, DepthFrame


class MockCameraDriver(CameraDriver):

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        # Fault injection
        disconnect_after_n_reads: int = 0,
        corrupt_every_n_frames: int = 0,
        depth_noise_sigma: float = 0.0,
        simulate_latency_sec: float = 0.0,
        start_disconnected: bool = False,
    ) -> None:
        super().__init__(width=width, height=height, fps=fps, driver_mode="mock")
        self._disconnect_after = disconnect_after_n_reads
        self._corrupt_every = corrupt_every_n_frames
        self._noise_sigma = depth_noise_sigma
        self._latency = simulate_latency_sec
        self._read_count = 0
        self._frame_index = 0
        self._start_disconnected = start_disconnected
        self._lock = threading.Lock()

    # ── DriverBase ─────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if self._start_disconnected:
            return False
        time.sleep(0.05)  # realistic connect latency
        return True

    def _do_disconnect(self) -> None:
        pass

    # ── CameraDriver ──────────────────────────────────────────────────────────

    def read_frames(self) -> tuple[ColorFrame | None, DepthFrame | None]:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")

        if self._latency > 0:
            time.sleep(self._latency)

        with self._lock:
            self._read_count += 1
            self._frame_index += 1
            n = self._read_count

        # Simulate USB disconnect
        if self._disconnect_after > 0 and n > self._disconnect_after:
            self._record_fault("USB_DISCONNECTED", "Simulated USB disconnect")
            raise DriverFault("USB disconnect", "USB_DISCONNECTED")

        # Generate colour frame: animated gradient
        t = time.monotonic()
        arr = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        arr[:, :, 0] = int(127 + 127 * math.sin(t))  # B oscillates
        arr[:, :, 1] = int(127 + 127 * math.cos(t * 0.7))  # G oscillates
        arr[:, :, 2] = 80  # R static

        # Corrupt every N frames
        if self._corrupt_every > 0 and self._frame_index % self._corrupt_every == 0:
            corrupt_region = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
            arr[100:150, 100:150] = corrupt_region

        color = ColorFrame(
            width=self.width,
            height=self.height,
            data=arr.tobytes(),
            encoding="bgr8",
        )

        # Generate depth frame: smooth bowl shape + noise
        yy, xx = np.mgrid[0 : self.height, 0 : self.width]
        cy, cx = self.height / 2, self.width / 2
        depth_arr = 1.5 + 1.0 * (((yy - cy) / cy) ** 2 + ((xx - cx) / cx) ** 2)
        depth_arr = depth_arr.astype(np.float32)
        if self._noise_sigma > 0:
            depth_arr += np.random.normal(0, self._noise_sigma, depth_arr.shape).astype(np.float32)

        depth = DepthFrame(
            width=self.width,
            height=self.height,
            data=depth_arr,
        )

        self._record_success()
        return color, depth

    def get_intrinsics(self) -> dict:
        # Realistic Astra Mini intrinsics
        return {
            "width": self.width,
            "height": self.height,
            "fx": 525.0,
            "fy": 525.0,
            "cx": self.width / 2,
            "cy": self.height / 2,
        }

    def inject_fault(self, **kwargs) -> None:
        """Runtime fault injection (for tests)."""
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
