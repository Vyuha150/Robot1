"""
Tests for bonbon_speech.audio.audio_preprocessor.AudioPreprocessor
"""

import numpy as np
import pytest
from bonbon_speech.audio.audio_preprocessor import AudioPreprocessor, PreprocessorConfig


def make_proc(**kwargs) -> AudioPreprocessor:
    return AudioPreprocessor(PreprocessorConfig(**kwargs))


# ── DC removal ────────────────────────────────────────────────────────────────


class TestDCRemoval:
    def test_removes_dc_offset(self):
        proc = make_proc(remove_dc_offset=True, normalise=False, noise_gate_enabled=False)
        samples = np.ones(512, dtype=np.float32) * 0.5
        out = proc.process(samples)
        assert abs(out.mean()) < 1e-6

    def test_dc_removal_preserves_ac_shape(self):
        proc = make_proc(remove_dc_offset=True, normalise=False, noise_gate_enabled=False)
        # Sine + DC offset
        t = np.linspace(0, 1, 512, dtype=np.float32)
        sine = np.sin(2 * np.pi * 100 * t).astype(np.float32)
        samples = sine + 0.3
        out = proc.process(samples)
        # DC removed; AC shape preserved (high correlation)
        corr = float(np.corrcoef(out, sine)[0, 1])
        assert corr > 0.99

    def test_dc_off(self):
        proc = make_proc(remove_dc_offset=False, normalise=False, noise_gate_enabled=False)
        samples = np.ones(512, dtype=np.float32) * 0.5
        out = proc.process(samples)
        assert abs(out.mean() - 0.5) < 1e-5


# ── Normalisation ─────────────────────────────────────────────────────────────


class TestNormalisation:
    def test_rms_normalise_target(self):
        proc = make_proc(
            remove_dc_offset=False,
            normalise=True,
            normalise_mode="rms",
            target_rms=0.1,
            noise_gate_enabled=False,
        )
        samples = np.random.randn(1024).astype(np.float32) * 5.0
        out = proc.process(samples)
        rms = proc.rms(out)
        assert abs(rms - 0.1) < 0.01

    def test_peak_normalise(self):
        proc = make_proc(
            remove_dc_offset=False, normalise=True, normalise_mode="peak", noise_gate_enabled=False
        )
        samples = np.array([0.0, 0.5, -0.25, 0.1], dtype=np.float32)
        out = proc.process(samples)
        assert abs(np.max(np.abs(out)) - 1.0) < 1e-5

    def test_silent_not_normalise_divide_by_zero(self):
        proc = make_proc(normalise=True)
        samples = np.zeros(512, dtype=np.float32)
        out = proc.process(samples)  # must not raise
        assert np.all(out == 0.0)

    def test_normalise_off(self):
        proc = make_proc(remove_dc_offset=False, normalise=False, noise_gate_enabled=False)
        samples = np.array([0.0, 0.1, 0.2], dtype=np.float32)
        out = proc.process(samples)
        np.testing.assert_array_almost_equal(out, samples)


# ── Noise gate ────────────────────────────────────────────────────────────────


class TestNoiseGate:
    def test_gate_zeros_below_floor(self):
        proc = make_proc(
            remove_dc_offset=False, normalise=False, noise_gate_enabled=True, noise_gate_floor=0.01
        )
        samples = np.array([0.005, -0.004, 0.02, -0.03], dtype=np.float32)
        out = proc.process(samples)
        assert out[0] == 0.0
        assert out[1] == 0.0
        assert out[2] == pytest.approx(0.02, abs=1e-5)
        assert out[3] == pytest.approx(-0.03, abs=1e-5)

    def test_gate_off_preserves_small_values(self):
        proc = make_proc(remove_dc_offset=False, normalise=False, noise_gate_enabled=False)
        samples = np.array([0.001, -0.002], dtype=np.float32)
        out = proc.process(samples)
        np.testing.assert_array_almost_equal(out, samples)


# ── Clamp ─────────────────────────────────────────────────────────────────────


class TestClamp:
    def test_clamps_to_minus1_plus1(self):
        proc = make_proc(remove_dc_offset=False, normalise=False, noise_gate_enabled=False)
        samples = np.array([5.0, -3.0, 0.5], dtype=np.float32)
        out = proc.process(samples)
        assert out[0] == pytest.approx(1.0)
        assert out[1] == pytest.approx(-1.0)
        assert out[2] == pytest.approx(0.5)


# ── Diagnostics ───────────────────────────────────────────────────────────────


class TestDiagnostics:
    def test_rms_known_value(self):
        proc = AudioPreprocessor()
        # RMS of sine(amplitude=1) over full cycle = 1/sqrt(2)
        t = np.linspace(0, 2 * np.pi, 10000, dtype=np.float32)
        sine = np.sin(t)
        rms = proc.rms(sine)
        assert abs(rms - 1.0 / np.sqrt(2)) < 0.01

    def test_rms_empty(self):
        proc = AudioPreprocessor()
        assert proc.rms(np.zeros(0, dtype=np.float32)) == 0.0

    def test_peak_known_value(self):
        proc = AudioPreprocessor()
        samples = np.array([-0.8, 0.3, 0.6], dtype=np.float32)
        assert proc.peak(samples) == pytest.approx(0.8)

    def test_peak_empty(self):
        proc = AudioPreprocessor()
        assert proc.peak(np.zeros(0, dtype=np.float32)) == 0.0

    def test_is_silent_true_on_zeros(self):
        proc = AudioPreprocessor()
        assert proc.is_silent(np.zeros(512, dtype=np.float32))

    def test_is_silent_false_on_speech(self):
        proc = AudioPreprocessor()
        samples = np.random.randn(512).astype(np.float32) * 0.1
        assert not proc.is_silent(samples)


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        proc = AudioPreprocessor()
        out = proc.process(np.zeros(0, dtype=np.float32))
        assert out.size == 0

    def test_2d_input_flattened(self):
        proc = make_proc(normalise=False, remove_dc_offset=False, noise_gate_enabled=False)
        samples = np.ones((2, 256), dtype=np.float32)
        out = proc.process(samples)
        assert out.ndim == 1
        assert out.shape[0] == 512

    def test_output_is_float32(self):
        proc = AudioPreprocessor()
        samples = np.random.randn(512).astype(np.float64)
        out = proc.process(samples)
        assert out.dtype == np.float32

    def test_input_not_mutated(self):
        proc = AudioPreprocessor()
        samples = np.ones(256, dtype=np.float32) * 0.5
        original = samples.copy()
        proc.process(samples)
        np.testing.assert_array_equal(samples, original)

    def test_single_sample(self):
        proc = make_proc(normalise=False, remove_dc_offset=True, noise_gate_enabled=False)
        samples = np.array([0.5], dtype=np.float32)
        out = proc.process(samples)
        # DC of a single sample is itself → result is 0
        assert out[0] == pytest.approx(0.0)
