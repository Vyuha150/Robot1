"""Unit tests for the generic USB camera + microphone drivers (Raspberry Pi).

Hardware (OpenCV / sounddevice) is mocked so these run on any CI box. They
verify graceful degradation when the SDK is missing, correct frame/chunk
shaping when it is present, and fault behaviour on disconnect.
"""

from __future__ import annotations

import sys
import types

import pytest

from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.camera import usb_camera_driver as ucd
from bonbon_hal.drivers.microphone import usb_mic_driver as umd
from bonbon_hal.drivers.camera.usb_camera_driver import UsbCameraDriver
from bonbon_hal.drivers.microphone.usb_mic_driver import UsbMicDriver


# ── Camera ─────────────────────────────────────────────────────────────────────

class _FakeCap:
    def __init__(self, frames=1, w=640, h=480):
        self._frames = frames
        self._w, self._h = w, h
        self.released = False

    def isOpened(self):  # noqa: N802
        return True

    def set(self, *_a):  # noqa: D401
        return True

    def get(self, prop):
        # width=3, height=4, fps=5 (cv2 enum values) — return sane numbers.
        return {3: self._w, 4: self._h, 5: 30.0}.get(prop, 0.0)

    def read(self):
        if self._frames <= 0:
            return (False, None)
        self._frames -= 1
        import numpy as np
        return (True, np.zeros((self._h, self._w, 3), dtype=np.uint8))

    def release(self):
        self.released = True


def _install_fake_cv2(monkeypatch, cap):
    fake = types.ModuleType("cv2")
    fake.CAP_V4L2 = 200
    fake.CAP_PROP_FOURCC = 6
    fake.CAP_PROP_FRAME_WIDTH = 3
    fake.CAP_PROP_FRAME_HEIGHT = 4
    fake.CAP_PROP_FPS = 5
    fake.CAP_PROP_BUFFERSIZE = 38
    fake.VideoWriter_fourcc = lambda *a: 0
    fake.VideoCapture = lambda *a, **k: cap
    monkeypatch.setattr(ucd, "cv2", fake, raising=False)
    monkeypatch.setattr(ucd, "_HAS_CV2", True, raising=False)


class TestUsbCamera:
    def test_missing_cv2_raises_clear_fault(self, monkeypatch):
        monkeypatch.setattr(ucd, "_HAS_CV2", False, raising=False)
        cam = UsbCameraDriver(device=0)
        with pytest.raises(DriverFault) as ei:
            cam._do_connect()
        assert ei.value.error_code == "SDK_MISSING"

    def test_connect_and_read_frame(self, monkeypatch):
        cap = _FakeCap(frames=10, w=640, h=480)
        _install_fake_cv2(monkeypatch, cap)
        cam = UsbCameraDriver(device=0, width=640, height=480)
        assert cam._do_connect() is True
        color, depth = cam.read_frames()
        assert depth is None                 # monocular USB cam → no depth
        assert color is not None
        assert color.width == 640 and color.height == 480
        assert color.encoding == "bgr8"
        assert len(color.data) == 640 * 480 * 3

    def test_disconnect_releases(self, monkeypatch):
        cap = _FakeCap(frames=5)
        _install_fake_cv2(monkeypatch, cap)
        cam = UsbCameraDriver(device=0)
        cam._do_connect()
        cam._do_disconnect()
        assert cap.released is True

    def test_sustained_frame_failure_raises(self, monkeypatch):
        cap = _FakeCap(frames=1)  # one warmup frame, then no more
        _install_fake_cv2(monkeypatch, cap)
        cam = UsbCameraDriver(device=0)
        cam._do_connect()         # consumes the 1 warmup frame
        # Next reads all fail → after 5 it raises.
        with pytest.raises(DriverFault):
            for _ in range(6):
                cam.read_frames()

    def test_intrinsics_from_fov(self):
        cam = UsbCameraDriver(device=0, width=640, height=480, hfov_deg=60.0)
        intr = cam.get_intrinsics()
        assert intr["width"] == 640 and intr["height"] == 480
        assert intr["cx"] == 320 and intr["cy"] == 240
        assert 500 < intr["fx"] < 600       # ~554 for 60° @ 640px


# ── Microphone ─────────────────────────────────────────────────────────────────

class _FakeStream:
    def __init__(self, fail=False):
        self.fail = fail
        self.started = self.closed = False

    def start(self): self.started = True
    def stop(self): pass
    def close(self): self.closed = True

    def read(self, n):
        if self.fail:
            raise RuntimeError("device gone")
        import numpy as np
        return (np.zeros((n, 1), dtype=np.int16), False)


def _install_fake_sd(monkeypatch, stream):
    fake = types.ModuleType("sounddevice")
    fake.InputStream = lambda **k: stream
    monkeypatch.setattr(umd, "sd", fake, raising=False)
    monkeypatch.setattr(umd, "_HAS_SD", True, raising=False)
    import numpy as np
    monkeypatch.setattr(umd, "np", np, raising=False)


class TestUsbMic:
    def test_missing_sd_raises_clear_fault(self, monkeypatch):
        monkeypatch.setattr(umd, "_HAS_SD", False, raising=False)
        mic = UsbMicDriver()
        with pytest.raises(DriverFault) as ei:
            mic._do_connect()
        assert ei.value.error_code == "SDK_MISSING"

    def test_connect_and_read_chunk(self, monkeypatch):
        stream = _FakeStream()
        _install_fake_sd(monkeypatch, stream)
        mic = UsbMicDriver(sample_rate=16000, channels=1)
        assert mic._do_connect() is True
        chunk = mic.read_chunk(1024)
        assert chunk.sample_rate == 16000
        assert chunk.channels == 1
        assert len(chunk.data) == 1024 * 2     # int16 mono → 2 bytes/sample
        assert chunk.device_id == "usb_mic"

    def test_transient_read_failure_returns_silence(self, monkeypatch):
        stream = _FakeStream(fail=True)
        _install_fake_sd(monkeypatch, stream)
        mic = UsbMicDriver()
        mic._do_connect()
        chunk = mic.read_chunk(512)            # first failure → silence, no raise
        assert set(chunk.data) == {0}

    def test_sustained_read_failure_raises(self, monkeypatch):
        stream = _FakeStream(fail=True)
        _install_fake_sd(monkeypatch, stream)
        mic = UsbMicDriver()
        mic._do_connect()
        with pytest.raises(DriverFault):
            for _ in range(6):
                mic.read_chunk(256)

    def test_led_angle_is_noop(self):
        mic = UsbMicDriver()
        assert mic.set_led_angle(90.0) is None

    def test_disconnect_closes(self, monkeypatch):
        stream = _FakeStream()
        _install_fake_sd(monkeypatch, stream)
        mic = UsbMicDriver()
        mic._do_connect()
        mic._do_disconnect()
        assert stream.closed is True
