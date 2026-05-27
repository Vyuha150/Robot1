"""
test_microphone_speaker.py
==========================
Tests for MockMicDriver and MockSpeakerDriver:
normal reads, USB disconnect, corruption, play recording, volume.
"""

from __future__ import annotations

import struct
import time

import pytest
from bonbon_hal.base.driver_base import DriverFault
from bonbon_hal.drivers.microphone import AudioChunk, MockMicDriver
from bonbon_hal.drivers.microphone.mic_driver import AudioChunk as AC
from bonbon_hal.drivers.speaker import MockSpeakerDriver

# ── Microphone ────────────────────────────────────────────────────────────────


@pytest.fixture
def mic() -> MockMicDriver:
    d = MockMicDriver()
    d.connect()
    return d


class TestMockMicNormal:
    def test_connect_ok(self, mic):
        assert mic.is_connected

    def test_read_chunk_returns_audio(self, mic):
        chunk = mic.read_chunk(512)
        assert isinstance(chunk, AudioChunk)

    def test_chunk_byte_length(self, mic):
        chunk = mic.read_chunk(512)
        expected = 512 * 1 * 2  # 512 frames × 1 ch × 2 bytes/sample
        assert len(chunk.data) == expected

    def test_num_samples_property(self, mic):
        chunk = mic.read_chunk(1024)
        assert chunk.num_samples == 1024

    def test_duration_property(self, mic):
        chunk = mic.read_chunk(1600)
        assert chunk.duration_sec == pytest.approx(0.1, abs=0.01)

    def test_multichannel_chunk(self):
        mic = MockMicDriver(sample_rate=16000, channels=4)
        mic.connect()
        chunk = mic.read_chunk(512)
        assert chunk.channels == 4
        assert len(chunk.data) == 512 * 4 * 2

    def test_tone_injection(self):
        mic = MockMicDriver(inject_tone_hz=440.0)
        mic.connect()
        chunk = mic.read_chunk(1024)
        # Speech VAD should be True when tone is injected
        assert chunk.is_speech is True

    def test_doa_angle_returned(self, mic):
        chunk = mic.read_chunk(512)
        assert chunk.doa_angle_deg == pytest.approx(45.0)

    def test_set_led_angle_no_error(self, mic):
        mic.set_led_angle(90.0)  # should not raise


class TestMockMicFaults:
    def test_read_without_connect_raises(self):
        mic = MockMicDriver()
        with pytest.raises(DriverFault):
            mic.read_chunk()

    def test_usb_disconnect_after_n(self):
        mic = MockMicDriver(disconnect_after_n=3)
        mic.connect()
        for _ in range(3):
            mic.read_chunk()
        with pytest.raises(DriverFault) as exc:
            mic.read_chunk()
        assert exc.value.error_code == "USB_DISCONNECTED"

    def test_corrupt_chunk(self):
        mic = MockMicDriver(corrupt_every_n=2)
        mic.connect()
        mic.read_chunk()  # chunk 1 — clean
        chunk = mic.read_chunk()  # chunk 2 — corrupt
        # Corrupt data: sample values are random bytes — check it doesn't raise
        samples = struct.unpack(f"<{len(chunk.data)//2}h", chunk.data)
        assert len(samples) > 0  # just verify we got data back

    def test_latency_simulation(self):
        mic = MockMicDriver(simulate_latency_sec=0.05)
        mic.connect()
        t0 = time.monotonic()
        mic.read_chunk()
        assert time.monotonic() - t0 >= 0.04


class TestMockMicRecovery:
    def test_reconnect_after_disconnect(self):
        mic = MockMicDriver(disconnect_after_n=2)
        mic.connect()
        mic.read_chunk()
        mic.read_chunk()
        try:
            mic.read_chunk()
        except DriverFault:
            pass
        mic.inject_fault(disc_after=0)
        ok = mic.reconnect()
        assert ok
        chunk = mic.read_chunk()
        assert isinstance(chunk, AudioChunk)


# ── Speaker ───────────────────────────────────────────────────────────────────


@pytest.fixture
def speaker() -> MockSpeakerDriver:
    d = MockSpeakerDriver()
    d.connect()
    return d


def _make_chunk(frames: int = 1024) -> AC:
    raw = struct.pack(f"<{frames}h", *([0] * frames))
    return AC(data=raw, sample_rate=16000, channels=1)


class TestMockSpeakerNormal:
    def test_connect_ok(self, speaker):
        assert speaker.is_connected

    def test_play_records_chunk(self, speaker):
        chunk = _make_chunk()
        speaker.play(chunk)
        assert len(speaker.played_chunks) == 1

    def test_multiple_play_calls(self, speaker):
        for _ in range(5):
            speaker.play(_make_chunk())
        assert len(speaker.played_chunks) == 5

    def test_set_volume(self, speaker):
        speaker.set_volume(50.0)
        assert speaker.volume_log[-1] == 50.0

    def test_volume_clamped(self, speaker):
        speaker.set_volume(200.0)
        assert speaker.volume_log[-1] == 100.0
        speaker.set_volume(-10.0)
        assert speaker.volume_log[-1] == 0.0

    def test_stop_sets_flag(self, speaker):
        speaker.stop()
        assert speaker.stopped is True

    def test_reset_log(self, speaker):
        speaker.play(_make_chunk())
        speaker.reset_log()
        assert len(speaker.played_chunks) == 0
        assert not speaker.stopped


class TestMockSpeakerFaults:
    def test_play_without_connect_raises(self):
        speaker = MockSpeakerDriver()
        with pytest.raises(DriverFault):
            speaker.play(_make_chunk())

    def test_fail_on_play(self):
        speaker = MockSpeakerDriver(fail_on_play=True)
        speaker.connect()
        with pytest.raises(DriverFault) as exc:
            speaker.play(_make_chunk())
        assert exc.value.error_code == "PLAY_ERROR"

    def test_play_file_missing(self, speaker):
        with pytest.raises(DriverFault) as exc:
            speaker.play_file("/nonexistent/path/audio.wav")
        assert exc.value.error_code == "FILE_NOT_FOUND"
