"""
Mock microphone driver — generates synthetic audio (silence + optional tone).

Fault injection:
  inject_noise_amplitude : white noise amplitude (0–1)
  inject_tone_hz         : insert a sine tone at this frequency
  disconnect_after_n     : simulate USB disconnect
  simulate_latency_sec   : artificial read latency
  corrupt_every_n        : corrupt every N chunks with random bytes
"""

from __future__ import annotations

import math
import random
import struct
import time

from bonbon_hal.base.driver_base import DriverFault

from .mic_driver import AudioChunk, MicDriver


class MockMicDriver(MicDriver):

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        inject_noise_amplitude: float = 0.02,
        inject_tone_hz: float = 0.0,
        doa_angle_deg: float = 45.0,
        disconnect_after_n: int = 0,
        simulate_latency_sec: float = 0.0,
        corrupt_every_n: int = 0,
        start_disconnected: bool = False,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._sample_rate = sample_rate
        self._channels = channels
        self._noise_amp = inject_noise_amplitude
        self._tone_hz = inject_tone_hz
        self._doa = doa_angle_deg
        self._disc_after = disconnect_after_n
        self._latency = simulate_latency_sec
        self._corrupt_n = corrupt_every_n
        self._start_disc = start_disconnected
        self._read_count = 0
        self._phase = 0.0

    def _do_connect(self) -> bool:
        if self._start_disc:
            return False
        time.sleep(0.05)
        return True

    def _do_disconnect(self) -> None:
        pass

    def read_chunk(self, num_frames: int = 1024) -> AudioChunk:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._latency:
            time.sleep(self._latency)

        self._read_count += 1
        n = self._read_count

        if self._disc_after > 0 and n > self._disc_after:
            self._record_fault("USB_DISCONNECTED", "Simulated USB disconnect")
            raise DriverFault("USB disconnect", "USB_DISCONNECTED")

        samples = []
        for _i in range(num_frames * self._channels):
            s = random.gauss(0, self._noise_amp) if self._noise_amp > 0 else 0.0
            if self._tone_hz > 0:
                s += 0.3 * math.sin(2 * math.pi * self._phase)
                self._phase += self._tone_hz / self._sample_rate
            s = max(-1.0, min(1.0, s))
            samples.append(int(s * 32767))

        raw = struct.pack(f"<{len(samples)}h", *samples)

        if self._corrupt_n > 0 and n % self._corrupt_n == 0:
            raw = bytes(random.randint(0, 255) for _ in range(len(raw)))

        self._record_success()
        return AudioChunk(
            data=raw,
            sample_rate=self._sample_rate,
            channels=self._channels,
            doa_angle_deg=self._doa,
            is_speech=(self._tone_hz > 0),
            device_id="mock_mic",
        )

    def set_led_angle(self, angle_deg: float) -> None:
        pass  # No-op in simulation

    def inject_fault(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
