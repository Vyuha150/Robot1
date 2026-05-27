"""
ReSpeaker v2.0 USB microphone array driver.

Hardware: XVSM-2000 4-mic linear array, USB HID + audio
SDK:      pyusb (pip install pyusb)  +  sounddevice (pip install sounddevice)
          or raw ALSA via sounddevice

The ReSpeaker v2.0 exposes:
  - USB Audio Class device: captures 6-channel audio (4 raw + 1 processed + 1 echo-ref)
  - USB HID interface: DOA angle readout via control transfers

We capture channel 0 (processed mono ASR channel) and DOA from HID.
"""

from __future__ import annotations

import logging
import struct

from bonbon_hal.base.driver_base import DriverFault

from .mic_driver import AudioChunk, MicDriver

logger = logging.getLogger(__name__)

# ReSpeaker v2.0 USB IDs
_RESPEAKER_VID = 0x2886
_RESPEAKER_PID = 0x0018

_HAS_USB = False
_HAS_SD = False
try:
    import usb.core  # type: ignore[import]
    import usb.util  # type: ignore[import]

    _HAS_USB = True
except ImportError:
    logger.warning("pyusb not installed. pip install pyusb")

try:
    import numpy as np
    import sounddevice as sd  # type: ignore[import]

    _HAS_SD = True
except ImportError:
    logger.warning("sounddevice not installed. pip install sounddevice numpy")


class RespeakerDriver(MicDriver):
    """
    ReSpeaker v2.0 4-mic array driver.

    Captures audio via sounddevice (ALSA), reads DOA via USB HID.
    """

    DOA_CMD = b"\x00\x1b"  # vendor command to read DOA angle

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_frames: int = 1024,
        device_name: str = "ReSpeaker",  # partial name match
        channel: int = 0,  # 0 = processed ASR mono
    ) -> None:
        super().__init__(driver_mode="real")
        self._sample_rate = sample_rate
        self._chunk_frames = chunk_frames
        self._device_name = device_name
        self._channel = channel
        self._device_index = None
        self._usb_dev = None
        self._stream = None
        self._buffer = None

    def _do_connect(self) -> bool:
        if not _HAS_SD:
            raise DriverFault("sounddevice not installed", "SDK_MISSING", recoverable=False)
        try:
            # Find sounddevice device index
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if self._device_name.lower() in dev["name"].lower():
                    self._device_index = i
                    break
            if self._device_index is None:
                raise DriverFault(
                    f"Audio device '{self._device_name}' not found",
                    "DEVICE_NOT_FOUND",
                )
            logger.info(
                "RespeakerDriver: using audio device %d: %s",
                self._device_index,
                sd.query_devices(self._device_index)["name"],
            )

            # Try to find USB HID for DOA
            if _HAS_USB:
                self._usb_dev = usb.core.find(idVendor=_RESPEAKER_VID, idProduct=_RESPEAKER_PID)
                if self._usb_dev:
                    try:
                        self._usb_dev.set_configuration()
                        logger.info("RespeakerDriver: USB HID DOA interface found")
                    except Exception as exc:
                        logger.warning("Could not configure USB HID: %s", exc)
                        self._usb_dev = None
            return True
        except DriverFault:
            raise
        except Exception as exc:
            raise DriverFault(str(exc), "CONNECT_ERROR") from exc

    def _do_disconnect(self) -> None:
        try:
            if self._stream:
                self._stream.close()
        except Exception:
            pass
        finally:
            self._stream = None
            self._usb_dev = None
            self._device_index = None

    def read_chunk(self, num_frames: int = 1024) -> AudioChunk:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        try:
            data, _ = sd.rec(
                frames=num_frames,
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                device=self._device_index,
                blocking=True,
            )
            raw = data.tobytes()
            doa = self._read_doa()
            self._record_success()
            return AudioChunk(
                data=raw,
                sample_rate=self._sample_rate,
                channels=1,
                doa_angle_deg=doa,
                device_id="respeaker",
            )
        except Exception as exc:
            self._record_fault("READ_ERROR", str(exc))
            raise DriverFault(str(exc), "READ_ERROR") from exc

    def set_led_angle(self, angle_deg: float) -> None:
        """Set ReSpeaker LED ring to point toward angle_deg (not implemented)."""
        pass

    def _read_doa(self) -> float:
        """Read direction-of-arrival angle from USB HID (0–359 degrees)."""
        if not self._usb_dev:
            return -1.0
        try:
            result = self._usb_dev.ctrl_transfer(0xC0, 0, 0x1B, 0, 2)
            angle = struct.unpack("<H", bytes(result))[0] / 10.0
            return float(angle)
        except Exception:
            return -1.0
