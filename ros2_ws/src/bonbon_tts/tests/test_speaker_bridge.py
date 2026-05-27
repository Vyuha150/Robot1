"""
tests/test_speaker_bridge.py
=============================
Unit tests for MockSpeakerBridge.

SpeakerBridge (HAL) is not tested here because it requires bonbon_hal
and a real audio device.  The interface contract is verified via the
mock double.
"""

import io
import wave

import pytest
from bonbon_tts.speaker.speaker_bridge import MockSpeakerBridge


def _make_wav(duration_sec: float = 0.1, sample_rate: int = 22050) -> bytes:
    """Create a minimal silent WAV for testing."""
    n = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


class TestMockSpeakerBridge:
    def test_initial_state(self):
        s = MockSpeakerBridge()
        assert s.play_count == 0
        assert s.stop_count == 0
        assert not s.is_playing()
        assert s.is_available()

    def test_play_records_wav(self):
        s = MockSpeakerBridge()
        wav = _make_wav()
        s.play(wav)
        assert s.play_count == 1
        assert s.play_calls[0] == wav

    def test_multiple_plays(self):
        s = MockSpeakerBridge()
        for _ in range(3):
            s.play(_make_wav())
        assert s.play_count == 3

    def test_stop_increments_count(self):
        s = MockSpeakerBridge()
        s.stop()
        s.stop()
        assert s.stop_count == 2

    def test_fail_next_play(self):
        s = MockSpeakerBridge()
        s.fail_next_play = True
        with pytest.raises(RuntimeError, match="Simulated speaker failure"):
            s.play(_make_wav())
        # Next play should succeed
        s.play(_make_wav())
        assert s.play_count == 1  # only the successful one counted

    def test_play_duration_accumulated(self):
        s = MockSpeakerBridge()
        wav = _make_wav(duration_sec=0.5)
        s.play(wav)
        s.play(wav)
        assert s.playing_duration_sec == pytest.approx(1.0, abs=0.01)

    def test_unavailable(self):
        s = MockSpeakerBridge(available=False)
        assert not s.is_available()

    def test_reset_clears_state(self):
        s = MockSpeakerBridge()
        s.play(_make_wav())
        s.stop()
        s.reset()
        assert s.play_count == 0
        assert s.stop_count == 0
        assert s.playing_duration_sec == pytest.approx(0.0)

    def test_backend_name(self):
        s = MockSpeakerBridge()
        assert s.backend_name() == "mock_speaker"

    def test_blocking_simulation(self):
        """simulate_play_blocking=True makes play() sleep for WAV duration."""
        import time

        s = MockSpeakerBridge(simulate_play_blocking=True)
        wav = _make_wav(duration_sec=0.05)
        t0 = time.monotonic()
        s.play(wav)
        elapsed = time.monotonic() - t0
        # Should have slept at least 40ms (generous lower bound for CI)
        assert elapsed >= 0.04

    def test_wav_duration_parsing(self):
        """_wav_duration should correctly extract WAV file duration."""
        wav = _make_wav(duration_sec=0.25, sample_rate=22050)
        dur = MockSpeakerBridge._wav_duration(wav)
        assert dur == pytest.approx(0.25, abs=0.01)

    def test_wav_duration_bad_bytes(self):
        """_wav_duration returns 0.0 for malformed input."""
        dur = MockSpeakerBridge._wav_duration(b"not a wav file")
        assert dur == pytest.approx(0.0)
