"""Abstract microphone driver — ReSpeaker v2.0 USB mic array."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field

from bonbon_hal.base.driver_base import DriverBase


@dataclass
class AudioChunk:
    data: bytes  # raw PCM int16 LE samples, interleaved
    sample_rate: int = 16000
    channels: int = 1  # 1 = processed mono; 4 = raw array
    bit_depth: int = 16
    doa_angle_deg: float = -1.0  # Direction of Arrival; -1 = unknown
    is_speech: bool = False  # VAD flag from firmware
    device_id: str = "mic"
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def num_samples(self) -> int:
        return len(self.data) // (self.bit_depth // 8) // self.channels

    @property
    def duration_sec(self) -> float:
        return self.num_samples / self.sample_rate


class MicDriver(DriverBase):
    def __init__(self, **kwargs) -> None:
        super().__init__("microphone", **kwargs)

    @abstractmethod
    def read_chunk(self, num_frames: int = 1024) -> AudioChunk:
        """
        Read one audio chunk of `num_frames` samples per channel.
        Raises DriverFault on hardware error.
        """

    @abstractmethod
    def set_led_angle(self, angle_deg: float) -> None:
        """Point the LED ring indicator toward angle_deg (ReSpeaker feature)."""
