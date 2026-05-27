"""
Tests for the VAD layer:
  - MockVAD state machine
  - Silence handling
  - Noisy audio (no false speech triggers)
  - Speech emission
  - Force-cut (max_speech_sec)
  - Wrong-wake-word flow (not triggering speech)
  - AudioSegment fields
"""

import time

import numpy as np
import pytest
from bonbon_speech.vad.base_vad import AudioSegment
from bonbon_speech.vad.mock_vad import MockVAD


def silence_chunk(n: int = 512) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def noise_chunk(n: int = 512, amplitude: float = 0.01) -> np.ndarray:
    """Low-amplitude Gaussian noise — should not trigger speech."""
    rng = np.random.default_rng(42)
    return (rng.standard_normal(n) * amplitude).astype(np.float32)


def speech_chunk(n: int = 512) -> np.ndarray:
    t = np.linspace(0, 1, n, dtype=np.float32)
    return np.sin(2 * np.pi * 300 * t) * 0.5


# ── AudioSegment ──────────────────────────────────────────────────────────────


class TestAudioSegment:
    def test_duration_computed_from_samples(self):
        samples = np.zeros(16000, dtype=np.float32)
        seg = AudioSegment(samples=samples, sample_rate=16000)
        assert seg.duration_sec == pytest.approx(1.0)

    def test_explicit_duration_respected(self):
        samples = np.zeros(16000, dtype=np.float32)
        seg = AudioSegment(samples=samples, sample_rate=16000, duration_sec=2.5)
        assert seg.duration_sec == pytest.approx(2.5)

    def test_onset_time_set(self):
        before = time.monotonic()
        seg = AudioSegment()
        after = time.monotonic()
        assert before <= seg.onset_time <= after

    def test_force_cut_default_false(self):
        assert AudioSegment().force_cut is False

    def test_doa_default_zero(self):
        assert AudioSegment().doa_angle_deg == pytest.approx(0.0)


# ── MockVAD: silence ─────────────────────────────────────────────────────────


class TestMockVADSilence:
    def test_all_silence_no_emission(self):
        vad = MockVAD(speech_pattern=[False] * 20)
        vad.load()
        for _ in range(20):
            vad.process_chunk(silence_chunk())
        assert vad.emit_count == 0

    def test_empty_pattern_defaults_to_silence(self):
        vad = MockVAD()
        vad.load()
        for _ in range(10):
            assert vad.process_chunk(silence_chunk()) is None


# ── MockVAD: speech emission ──────────────────────────────────────────────────


class TestMockVADSpeech:
    def test_speech_then_silence_emits_segment(self):
        pattern = [True] * 10 + [False] * 5
        vad = MockVAD(speech_pattern=pattern)
        vad.load()
        emitted = None
        for _ in range(len(pattern)):
            seg = vad.process_chunk(speech_chunk())
            if seg is not None:
                emitted = seg
        assert emitted is not None
        assert emitted.duration_sec > 0.0
        assert not emitted.force_cut

    def test_emit_accumulates_samples(self):
        pattern = [True] * 8 + [False] * 2
        vad = MockVAD(speech_pattern=pattern)
        vad.load()
        seg = None
        for _ in range(len(pattern)):
            result = vad.process_chunk(speech_chunk(512))
            if result is not None:
                seg = result
        assert seg is not None
        # 8 speech chunks * 512 samples each
        assert seg.samples.shape[0] == 8 * 512

    def test_doa_passed_through(self):
        vad = MockVAD()
        vad.load()
        vad.force_next_emit(samples=np.zeros(512, dtype=np.float32))
        seg = vad.process_chunk(silence_chunk(), doa_angle_deg=45.0)
        assert seg is not None
        assert seg.doa_angle_deg == pytest.approx(45.0)

    def test_multiple_speech_segments(self):
        pattern = ([True] * 5 + [False] * 3) * 3
        vad = MockVAD(speech_pattern=pattern)
        vad.load()
        for chunk in [speech_chunk(512)] * len(pattern):
            vad.process_chunk(chunk)
        assert vad.emit_count == 3

    def test_call_count_increments(self):
        vad = MockVAD()
        vad.load()
        for _ in range(7):
            vad.process_chunk(silence_chunk())
        assert vad.call_count == 7


# ── MockVAD: force emit ───────────────────────────────────────────────────────


class TestMockVADForceEmit:
    def test_force_emit_returns_segment(self):
        vad = MockVAD()
        vad.load()
        samples = np.ones(512, dtype=np.float32)
        vad.force_next_emit(samples=samples)
        seg = vad.process_chunk(silence_chunk())
        assert seg is not None
        np.testing.assert_array_almost_equal(seg.samples, samples)

    def test_force_cut_flag_set(self):
        vad = MockVAD()
        vad.load()
        vad.force_next_emit(force_cut=True)
        seg = vad.process_chunk(silence_chunk())
        assert seg.force_cut is True

    def test_force_emit_only_once(self):
        vad = MockVAD()
        vad.load()
        vad.force_next_emit()
        vad.process_chunk(silence_chunk())  # consumes it
        seg2 = vad.process_chunk(silence_chunk())
        assert seg2 is None


# ── MockVAD: set_speech_pattern ───────────────────────────────────────────────


class TestMockVADPattern:
    def test_pattern_cycles(self):
        vad = MockVAD(speech_pattern=[True, False])
        vad.load()
        # Feed 4 chunks — one cycle = emit once
        [vad.process_chunk(speech_chunk(512)) for _ in range(4)]
        # Should have emitted once (after True→False transition)
        assert vad.emit_count >= 1

    def test_set_speech_pattern_resets_index(self):
        vad = MockVAD(speech_pattern=[True, True])
        vad.load()
        vad.set_speech_pattern([False, False])
        for _ in range(4):
            vad.process_chunk(silence_chunk())
        assert vad.emit_count == 0


# ── MockVAD: reset ────────────────────────────────────────────────────────────


class TestMockVADReset:
    def test_reset_clears_state(self):
        pattern = [True] * 5  # partial speech, no silence → no emit yet
        vad = MockVAD(speech_pattern=pattern)
        vad.load()
        for _ in range(5):
            vad.process_chunk(speech_chunk())
        assert vad.emit_count == 0  # not emitted yet
        vad.reset()
        # After reset, pattern index restarts; another run of all-speech
        for _ in range(5):
            vad.process_chunk(speech_chunk())
        # Still 0 — pattern never transitions to False
        assert vad.emit_count == 0

    def test_unload_resets(self):
        vad = MockVAD()
        vad.load()
        vad.unload()
        assert not vad.loaded


# ── Noisy audio ───────────────────────────────────────────────────────────────


class TestNoisyAudio:
    def test_low_amplitude_noise_no_emission(self):
        """Low-amplitude noise must not cause MockVAD to emit (all-silence pattern)."""
        vad = MockVAD(speech_pattern=[False] * 50)
        vad.load()
        for _ in range(50):
            seg = vad.process_chunk(noise_chunk(512, 0.005))
            assert seg is None

    def test_speech_in_noise_still_emits(self):
        """When speech pattern is set, noisy chunks are still processed."""
        pattern = [True] * 10 + [False] * 5
        vad = MockVAD(speech_pattern=pattern)
        vad.load()
        emitted = None
        for is_speech_step in pattern:
            chunk = (
                speech_chunk(512) + noise_chunk(512, 0.01)
                if is_speech_step
                else noise_chunk(512, 0.01)
            )
            seg = vad.process_chunk(chunk)
            if seg is not None:
                emitted = seg
        assert emitted is not None


# ── Wrong wake word (VAD isolation) ──────────────────────────────────────────


class TestWrongWakeWordFlow:
    """
    If the wake-word gating prevents speech from reaching the VAD,
    the VAD should never emit.  We simulate this by only pushing
    silence chunks (gate closed).
    """

    def test_silence_only_no_emission(self):
        vad = MockVAD(speech_pattern=[False] * 100)
        vad.load()
        for _ in range(100):
            seg = vad.process_chunk(silence_chunk())
            assert seg is None
        assert vad.emit_count == 0
