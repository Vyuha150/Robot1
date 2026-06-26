"""
Generic USB / ALSA microphone driver (sounddevice-backed).

For Raspberry Pi + any standard USB microphone or USB sound card. Captures
mono int16 PCM at the configured sample rate. No direction-of-arrival or LED
ring (those are ReSpeaker-only); ``set_led_angle`` is a no-op.

``sounddevice`` (PortAudio) is an optional import: if it is missing the driver
raises a clear ``DriverFault`` at connect time rather than at import.
"""

from __future__ import annotations

import logging
import time

from bonbon_hal.base.driver_base import DriverFault

from .mic_driver import AudioChunk, MicDriver

logger = logging.getLogger(__name__)

try:
    import numpy as np  # type: ignore[import]
    import sounddevice as sd  # type: ignore[import]
    _HAS_SD = True
except Exception:  # noqa: BLE001
    _HAS_SD = False


class UsbMicDriver(MicDriver):
    """USB / ALSA microphone via PortAudio (``sounddevice``).

    Args:
        device: PortAudio device index or name substring (``None`` → default
            input). On a Pi this is typically the USB mic, e.g. ``"USB"``.
        sample_rate: capture rate in Hz (16000 is required by the Silero VAD /
            Whisper pipeline downstream).
        channels: 1 = mono (recommended for a single USB mic).
        blocksize: frames per read; also the InputStream block size.
    """

    def __init__(
        self,
        device: int | str | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 1024,
        **kwargs,
    ) -> None:
        super().__init__(driver_mode="real", **kwargs)
        self._device = device
        self._sample_rate = sample_rate
        self._channels = channels
        self._blocksize = blocksize
        self._stream = None
        self._consecutive_failures = 0

    # ── DriverBase ────────────────────────────────────────────────────────────

    def _do_connect(self) -> bool:
        if not _HAS_SD:
            raise DriverFault(
                "sounddevice not installed — install with: pip install sounddevice",
                "SDK_MISSING", recoverable=False,
            )
        try:
            stream = sd.InputStream(
                device=self._device,
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=self._blocksize,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001
            raise DriverFault(
                f"could not open microphone {self._device!r}: {exc}",
                "DEVICE_OPEN_FAILED", recoverable=True,
            ) from exc
        self._stream = stream
        self._consecutive_failures = 0
        logger.info(
            "USB mic connected: device=%s %d Hz %dch", self._device,
            self._sample_rate, self._channels,
        )
        return True

    def _do_disconnect(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    # ── MicDriver ─────────────────────────────────────────────────────────────

    def read_chunk(self, num_frames: int = 1024) -> AudioChunk:
        if self._stream is None:
            raise DriverFault("microphone not connected", "NOT_CONNECTED", recoverable=True)
        try:
            data, overflowed = self._stream.read(num_frames)
        except Exception as exc:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures >= 5:
                raise DriverFault(
                    "microphone read failed 5x — likely disconnected",
                    "READ_FAILED", recoverable=True,
                ) from exc
            # Return silence on a transient hiccup rather than crashing.
            silence = (b"\x00\x00" * num_frames * self._channels)
            return AudioChunk(data=silence, sample_rate=self._sample_rate,
                              channels=self._channels, device_id="usb_mic")
        if overflowed:
            logger.debug("USB mic input overflow (dropped samples)")
        self._consecutive_failures = 0
        # data is an (frames, channels) int16 ndarray → interleaved bytes.
        pcm = np.ascontiguousarray(data, dtype=np.int16).tobytes()
        return AudioChunk(
            data=pcm, sample_rate=self._sample_rate, channels=self._channels,
            bit_depth=16, device_id="usb_mic", timestamp=time.monotonic(),
        )

    def set_led_angle(self, angle_deg: float) -> None:
        # No LED ring on a generic USB mic — no-op.
        return None
