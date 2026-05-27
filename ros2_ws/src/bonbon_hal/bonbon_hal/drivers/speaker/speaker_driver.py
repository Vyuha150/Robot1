"""Abstract speaker driver."""

from __future__ import annotations

from abc import abstractmethod

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.microphone.mic_driver import AudioChunk


class SpeakerDriver(DriverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__("speaker", **kwargs)

    @abstractmethod
    def play(self, chunk: AudioChunk) -> None:
        """
        Play audio chunk synchronously.
        Raises DriverFault on hardware error.
        """

    @abstractmethod
    def play_file(self, path: str) -> None:
        """
        Play a WAV/MP3 file.
        Raises DriverFault if file not found or playback fails.
        """

    @abstractmethod
    def set_volume(self, percent: float) -> None:
        """Set playback volume 0–100 %."""

    @abstractmethod
    def stop(self) -> None:
        """Interrupt any current playback immediately."""
