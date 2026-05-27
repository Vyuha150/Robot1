"""
Mock speaker driver — records play() calls for test assertion.

No audio hardware is accessed.  Tests can inspect played_chunks and
played_files to verify audio was sent.
"""

from __future__ import annotations

import os
import time

from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.microphone.mic_driver import AudioChunk

from .speaker_driver import SpeakerDriver


class MockSpeakerDriver(SpeakerDriver):

    def __init__(
        self,
        simulate_play_duration: bool = False,
        fail_on_play: bool = False,
        start_disconnected: bool = False,
    ) -> None:
        super().__init__(driver_mode="mock")
        self._sim_duration = simulate_play_duration
        self._fail_on_play = fail_on_play
        self._start_disc = start_disconnected
        self._volume = 80.0
        self._stopped = False

        # Inspection state (read in tests)
        self.played_chunks: list[AudioChunk] = []
        self.played_files: list[str] = []
        self.volume_log: list[float] = []

    def _do_connect(self) -> bool:
        return not self._start_disc

    def _do_disconnect(self) -> None:
        pass

    def play(self, chunk: AudioChunk) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if self._fail_on_play:
            self._record_fault("PLAY_ERROR", "Simulated play failure")
            raise DriverFault("Play failed", "PLAY_ERROR")
        self.played_chunks.append(chunk)
        if self._sim_duration:
            time.sleep(chunk.duration_sec)
        self._record_success()

    def play_file(self, path: str) -> None:
        if not self.is_connected:
            raise DriverFault("Not connected", "NOT_CONNECTED")
        if not os.path.exists(path):
            raise DriverFault(f"File not found: {path}", "FILE_NOT_FOUND")
        if self._fail_on_play:
            raise DriverFault("Play failed", "PLAY_ERROR")
        self.played_files.append(path)
        self._record_success()

    def set_volume(self, percent: float) -> None:
        self._volume = max(0.0, min(100.0, percent))
        self.volume_log.append(self._volume)

    def stop(self) -> None:
        self._stopped = True

    def reset_log(self) -> None:
        self.played_chunks.clear()
        self.played_files.clear()
        self.volume_log.clear()
        self._stopped = False
