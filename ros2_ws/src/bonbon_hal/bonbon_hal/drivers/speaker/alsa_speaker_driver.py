"""
ALSA speaker driver via sounddevice.

Plays AudioChunk objects and WAV files.
Volume control via amixer (ALSA) or sounddevice's output level.

SDK:  sounddevice (pip install sounddevice)
      pydub       (pip install pydub)  — for WAV/MP3 file playback
"""

from __future__ import annotations

import logging
import os
import subprocess

from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.microphone.mic_driver import AudioChunk

from .speaker_driver import SpeakerDriver

logger = logging.getLogger(__name__)

_HAS_SD = False
_HAS_NP = False
try:
    import numpy as np
    import sounddevice as sd  # type: ignore[import]

    _HAS_SD = True
    _HAS_NP = True
except ImportError:
    logger.warning("sounddevice/numpy not installed. pip install sounddevice numpy")

_HAS_PYDUB = False
try:
    from pydub import AudioSegment  # type: ignore[import]
    from pydub.playback import play as _pydub_play

    _HAS_PYDUB = True
except ImportError:
    logger.warning("pydub not installed.  pip install pydub  (WAV file playback disabled)")


class AlsaSpeakerDriver(SpeakerDriver):

    def __init__(
        self,
        device_name: str = "default",
        volume_pct: float = 80.0,
        amixer_control: str = "Master",
    ) -> None:
        super().__init__(driver_mode="real")
        self._device_name = device_name
        self._volume = volume_pct
        self._amixer_control = amixer_control
        self._device_index = None
        self._playing = False

    def _do_connect(self) -> bool:
        if not _HAS_SD:
            raise DriverFault("sounddevice not installed", "SDK_MISSING", recoverable=False)
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if (
                    self._device_name == "default"
                    or self._device_name.lower() in dev["name"].lower()
                ):
                    if dev["max_output_channels"] > 0:
                        self._device_index = i
                        break
            if self._device_index is None and self._device_name != "default":
                raise DriverFault(
                    f"Output device '{self._device_name}' not found",
                    "DEVICE_NOT_FOUND",
                )
            logger.info(
                "AlsaSpeakerDriver: using output device %s",
                (
                    sd.query_devices(self._device_index or "default")["name"]
                    if self._device_index is not None
                    else "default"
                ),
            )
            self.set_volume(self._volume)
            return True
        except DriverFault:
            raise
        except Exception as exc:
            raise DriverFault(str(exc), "CONNECT_ERROR") from exc

    def _do_disconnect(self) -> None:
        self.stop()

    def play(self, chunk: AudioChunk) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if not _HAS_NP:
            raise DriverFault("numpy not installed", "SDK_MISSING", recoverable=False)
        try:
            self._playing = True
            samples = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32) / 32768.0
            if chunk.channels > 1:
                samples = samples.reshape(-1, chunk.channels)
            sd.play(samples, samplerate=chunk.sample_rate, device=self._device_index, blocking=True)
            self._playing = False
            self._record_success()
        except Exception as exc:
            self._playing = False
            self._record_fault("PLAY_ERROR", str(exc))
            raise DriverFault(str(exc), "PLAY_ERROR") from exc

    def play_file(self, path: str) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if not os.path.exists(path):
            raise DriverFault(f"File not found: {path}", "FILE_NOT_FOUND")
        try:
            if _HAS_PYDUB:
                seg = AudioSegment.from_file(path)
                self._playing = True
                _pydub_play(seg)
                self._playing = False
            else:
                # Fall back to aplay (Linux ALSA CLI)
                result = subprocess.run(
                    ["aplay", "-D", self._device_name, path],
                    timeout=60,
                    capture_output=True,
                )
                if result.returncode != 0:
                    raise DriverFault(f"aplay failed: {result.stderr.decode()}", "PLAY_ERROR")
            self._record_success()
        except DriverFault:
            raise
        except Exception as exc:
            self._record_fault("PLAY_ERROR", str(exc))
            raise DriverFault(str(exc), "PLAY_ERROR") from exc

    def set_volume(self, percent: float) -> None:
        self._volume = max(0.0, min(100.0, percent))
        try:
            subprocess.run(
                ["amixer", "sset", self._amixer_control, f"{int(self._volume)}%"],
                capture_output=True,
                timeout=2,
            )
        except Exception as exc:
            logger.warning("amixer volume set failed: %s", exc)

    def stop(self) -> None:
        if _HAS_SD:
            try:
                sd.stop()
            except Exception:
                pass
        self._playing = False
