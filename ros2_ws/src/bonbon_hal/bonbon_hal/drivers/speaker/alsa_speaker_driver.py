"""
ALSA speaker driver via sounddevice, with optional PAM8610 amplifier
mute-pin control (Pi-2 hardware: 4Ω 10W speaker driven by a PAM8610
2x10W amp — see docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 4).

Plays AudioChunk objects and WAV files.
Volume control via amixer (ALSA) or sounddevice's output level — this is
signal-level gain, unrelated to the PAM8610's own mute/standby pin.

Whether the PAM8610 board's mute pin is actually wired to a Pi GPIO is
NOT assumed here: `has_pam8610` defaults to False, so behavior is
identical to before unless a real unit's config explicitly enables it
after hardware verification (per the gap report's own caveat). When
enabled, GPIO init failure degrades this ONE capability (logged, amp
control reported unavailable) rather than failing speaker connect()
entirely -- ALSA playback must keep working even if the amp's mute pin
turns out to be unreachable.

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

_SIMULATION = os.environ.get("BONBON_SIMULATION", "0") == "1"


class _MockGPIO:
    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def setmode(self, *a):
        pass

    def setup(self, *a, **kw):
        pass

    def cleanup(self):
        pass

    def output(self, pin, val):
        logger.debug("[MockGPIO] pin%d→%d", pin, val)


def _load_gpio():
    if _SIMULATION:
        logger.info("BONBON_SIMULATION=1: using MockGPIO for PAM8610 mute pin")
        return _MockGPIO()
    try:
        import Jetson.GPIO as GPIO  # type: ignore[import]

        return GPIO
    except ImportError:
        try:
            import RPi.GPIO as GPIO  # type: ignore[import]

            return GPIO
        except ImportError:
            logger.warning("No GPIO library found — falling back to MockGPIO")
            return _MockGPIO()


class AlsaSpeakerDriver(SpeakerDriver):

    def __init__(
        self,
        device_name: str = "default",
        volume_pct: float = 80.0,
        amixer_control: str = "Master",
        has_pam8610: bool = False,
        mute_pin: int = 23,
        mute_active_low: bool = True,
    ) -> None:
        super().__init__(driver_mode="real")
        self._device_name = device_name
        self._volume = volume_pct
        self._amixer_control = amixer_control
        self._device_index = None
        self._playing = False

        # PAM8610 amp mute-pin control (optional — see module docstring).
        self._has_pam8610 = has_pam8610
        self._mute_pin = mute_pin
        self._mute_active_low = mute_active_low
        self._pam8610_ready = False
        self._muted = False
        self._gpio = _load_gpio() if has_pam8610 else None

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
            self._init_pam8610()
            return True
        except DriverFault:
            raise
        except Exception as exc:
            raise DriverFault(str(exc), "CONNECT_ERROR") from exc

    def _init_pam8610(self) -> None:
        if not self._has_pam8610:
            return
        try:
            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setup(self._mute_pin, self._gpio.OUT)
            self._pam8610_ready = True
            self.unmute()
            logger.info("AlsaSpeakerDriver: PAM8610 mute pin %d ready", self._mute_pin)
        except Exception as exc:
            # Amp-control is an optional enhancement (see gap report) --
            # degrade THIS capability only, never fail speaker connect().
            self._pam8610_ready = False
            logger.warning(
                "AlsaSpeakerDriver: PAM8610 GPIO init failed (%s) — "
                "amp mute control unavailable, plain ALSA playback continues",
                exc,
            )
            self._record_partial_fault("PAM8610_GPIO_INIT_FAILED", str(exc))

    def _do_disconnect(self) -> None:
        self.stop()
        if self._pam8610_ready:
            try:
                self.mute()
                self._gpio.cleanup()
            except Exception:
                pass
            self._pam8610_ready = False

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

    # ── PAM8610 amp mute-pin control (no-op unless has_pam8610 AND GPIO
    #    init succeeded -- see _init_pam8610) ──────────────────────────────

    @property
    def has_pam8610_control(self) -> bool:
        """True only if PAM8610 mute-pin control was requested AND the
        GPIO pin was actually claimed successfully -- never fabricated."""
        return self._pam8610_ready

    @property
    def is_muted(self) -> bool:
        return self._muted

    def mute(self) -> None:
        if not self._pam8610_ready:
            return
        asserted = self._gpio.LOW if self._mute_active_low else self._gpio.HIGH
        self._gpio.output(self._mute_pin, asserted)
        self._muted = True

    def unmute(self) -> None:
        if not self._pam8610_ready:
            return
        asserted = self._gpio.HIGH if self._mute_active_low else self._gpio.LOW
        self._gpio.output(self._mute_pin, asserted)
        self._muted = False
