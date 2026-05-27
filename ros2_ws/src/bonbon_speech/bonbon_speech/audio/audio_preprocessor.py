"""
bonbon_speech.audio.audio_preprocessor
========================================
Audio preprocessing utilities applied to each AudioChunk before VAD.

Pipeline (configurable):
  1. DC offset removal  (subtract per-chunk mean)
  2. Amplitude normalisation  (peak or RMS, configurable)
  3. Optional noise-gate  (zero samples below a floor to reduce mic hiss)
  4. Clamp to [-1, 1] (protect downstream models from out-of-range input)

All operations are NumPy-based and run in-line on the ROS2 callback thread,
so they must be fast (< 1 ms for a 512-sample chunk at 16 kHz).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PreprocessorConfig:
    """Knobs for the audio preprocessor."""

    remove_dc_offset: bool = True
    normalise: bool = True
    # "peak" divides by max(abs); "rms" divides by RMS+eps
    normalise_mode: str = "rms"  # "peak" | "rms"
    # Target RMS level after normalisation (linear, not dB)
    target_rms: float = 0.1
    # Noise gate: samples with |amplitude| below this become 0
    noise_gate_enabled: bool = False
    noise_gate_floor: float = 0.005  # linear amplitude floor


class AudioPreprocessor:
    """
    Stateless (per-call) audio preprocessing for float32 mono PCM.

    Usage::

        proc = AudioPreprocessor(PreprocessorConfig())
        clean = proc.process(raw_samples)
    """

    def __init__(self, cfg: PreprocessorConfig | None = None) -> None:
        self._cfg = cfg or PreprocessorConfig()
        logger.debug(
            "AudioPreprocessor init dc=%s norm=%s/%s gate=%s",
            self._cfg.remove_dc_offset,
            self._cfg.normalise,
            self._cfg.normalise_mode,
            self._cfg.noise_gate_enabled,
        )

    # ── Main entry point ─────────────────────────────────────────────────────

    def process(self, samples: np.ndarray) -> np.ndarray:
        """
        Apply the configured preprocessing chain to *samples* (float32 1-D).

        Returns a new float32 array of the same length.
        The input array is never modified in-place.
        """
        if samples.ndim != 1:
            samples = samples.flatten()
        out = samples.astype(np.float32, copy=True)

        if out.size == 0:
            return out

        if self._cfg.remove_dc_offset:
            out = self._remove_dc(out)

        if self._cfg.noise_gate_enabled:
            out = self._noise_gate(out, self._cfg.noise_gate_floor)

        if self._cfg.normalise:
            out = self._normalise(out, self._cfg.normalise_mode, self._cfg.target_rms)

        # Hard clamp — safety net for edge cases
        out = np.clip(out, -1.0, 1.0)
        return out

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def rms(self, samples: np.ndarray) -> float:
        """Return the RMS amplitude of *samples* (0 if empty)."""
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

    def peak(self, samples: np.ndarray) -> float:
        """Return the peak absolute amplitude of *samples* (0 if empty)."""
        if samples.size == 0:
            return 0.0
        return float(np.max(np.abs(samples.astype(np.float64))))

    def is_silent(self, samples: np.ndarray, rms_floor: float = 1e-4) -> bool:
        """True when the chunk is effectively silent (all-zeros / near-silence)."""
        return self.rms(samples) < rms_floor

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _remove_dc(samples: np.ndarray) -> np.ndarray:
        return samples - samples.mean()

    @staticmethod
    def _noise_gate(samples: np.ndarray, floor: float) -> np.ndarray:
        out = samples.copy()
        out[np.abs(out) < floor] = 0.0
        return out

    @staticmethod
    def _normalise(samples: np.ndarray, mode: str, target_rms: float) -> np.ndarray:
        eps = 1e-9
        if mode == "peak":
            pk = np.max(np.abs(samples))
            if pk < eps:
                return samples
            return samples / pk
        else:  # rms (default)
            rms_val = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            if rms_val < eps:
                return samples
            return samples * (target_rms / rms_val)
