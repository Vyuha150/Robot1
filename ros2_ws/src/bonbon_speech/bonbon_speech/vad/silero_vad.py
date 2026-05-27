"""
bonbon_speech.vad.silero_vad
==============================
Silero VAD backend.

State machine
-------------
SILENCE  --> (prob >= speech_start_threshold for >= min_speech_frames) --> SPEECH
SPEECH   --> (prob < speech_end_threshold for >= silence_frames_to_end) --> emit
SPEECH   --> (total samples >= max_speech_sec * sample_rate) --> force-cut emit

The prebuffer snapshot from AudioBuffer is prepended so the segment includes
audio immediately before the detected onset.

Silero constraints (enforced upstream by AudioConfig.validate):
  * sample_rate in {8000, 16000}
  * chunk_size in {256, 512, 768, 1024, 1536}
"""

from __future__ import annotations

import logging
import time

import numpy as np

from bonbon_speech.config.speech_config import VADConfig
from bonbon_speech.vad.base_vad import AudioSegment, BaseVAD

logger = logging.getLogger(__name__)

_STATE_SILENCE = "SILENCE"
_STATE_MAYBE = "MAYBE_SPEECH"  # accumulating speech_start frames
_STATE_SPEECH = "SPEECH"
_STATE_MAYBE_END = "MAYBE_END"  # accumulating silence_end frames


class SileroVAD(BaseVAD):
    """Silero VAD with hysteresis state machine."""

    def __init__(self, cfg: VADConfig, sample_rate: int = 16000) -> None:
        super().__init__(sample_rate)
        self._cfg = cfg
        self._model = None
        self._state = _STATE_SILENCE

        # Accumulators
        self._speech_samples: list[float] = []
        self._maybe_speech_frames: int = 0
        self._silence_end_frames: int = 0
        self._onset_time: float = 0.0

        # silence pad buffer (samples captured after speech end for trailing phoneme)
        self._pad_samples_needed = int(cfg.speech_pad_ms / 1000.0 * sample_rate)
        self._pad_buf: list[float] = []

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._model is not None:
            return  # idempotent

        try:
            import torch

            if self._cfg.model_path:
                logger.info("SileroVAD loading from path=%s", self._cfg.model_path)
                self._model, _ = torch.hub.load(
                    repo_or_dir=self._cfg.model_path,
                    model="silero_vad",
                    source="local",
                    force_reload=False,
                    onnx=False,
                )
            else:
                logger.info("SileroVAD downloading from torch.hub …")
                self._model, _ = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    onnx=False,
                )
            self._model.eval()
            logger.info("SileroVAD model loaded ok")
        except Exception as exc:
            logger.error("SileroVAD load failed: %s", exc)
            raise

    def unload(self) -> None:
        self._model = None
        self.reset()
        logger.debug("SileroVAD unloaded")

    def reset(self) -> None:
        self._state = _STATE_SILENCE
        self._speech_samples.clear()
        self._maybe_speech_frames = 0
        self._silence_end_frames = 0
        self._pad_buf.clear()
        self._onset_time = 0.0
        if self._model is not None:
            try:
                self._model.reset_states()
            except Exception:
                pass

    # ── Core processing ──────────────────────────────────────────────────────

    def process_chunk(
        self,
        samples: np.ndarray,
        doa_angle_deg: float = 0.0,
    ) -> AudioSegment | None:
        """
        Feed one chunk; returns an AudioSegment when speech completes, else None.
        """
        if self._model is None:
            raise RuntimeError("SileroVAD.load() not called")

        try:
            import torch

            tensor = torch.from_numpy(samples.astype(np.float32))
            with torch.no_grad():
                prob = float(self._model(tensor, self._sample_rate).item())
        except Exception as exc:
            logger.warning("SileroVAD inference error: %s — treating as silence", exc)
            prob = 0.0

        return self._step(prob, samples, doa_angle_deg)

    # ── State machine ────────────────────────────────────────────────────────

    def _step(
        self,
        prob: float,
        samples: np.ndarray,
        doa_angle_deg: float,
    ) -> AudioSegment | None:
        cfg = self._cfg
        chunk = samples.tolist()

        if self._state == _STATE_SILENCE:
            if prob >= cfg.speech_start_threshold:
                self._maybe_speech_frames += 1
                self._speech_samples.extend(chunk)
                if self._maybe_speech_frames >= cfg.min_speech_frames:
                    self._state = _STATE_SPEECH
                    self._onset_time = time.monotonic()
                    self._silence_end_frames = 0
                    logger.debug(
                        "VAD SILENCE->SPEECH prob=%.3f frames=%d",
                        prob,
                        self._maybe_speech_frames,
                    )
            else:
                # Keep a rolling prebuffer of silence (last chunk only)
                self._maybe_speech_frames = 0
                self._speech_samples.clear()
            return None

        elif self._state == _STATE_SPEECH:
            self._speech_samples.extend(chunk)
            total_samples = len(self._speech_samples)
            max_samples = int(cfg.max_speech_sec * self._sample_rate)

            # Force cut: segment too long
            if total_samples >= max_samples:
                logger.info("VAD force-cut after %.1f sec", cfg.max_speech_sec)
                return self._emit(doa_angle_deg, force_cut=True)

            if prob < cfg.speech_end_threshold:
                self._silence_end_frames += 1
                if self._silence_end_frames >= cfg.silence_frames_to_end:
                    # Transition to pad accumulation
                    self._state = _STATE_MAYBE_END
                    self._pad_buf.clear()
                    logger.debug(
                        "VAD SPEECH->MAYBE_END prob=%.3f sil_frames=%d",
                        prob,
                        self._silence_end_frames,
                    )
            else:
                self._silence_end_frames = 0

            return None

        elif self._state == _STATE_MAYBE_END:
            # Accumulate speech_pad_ms of audio after silence is confirmed
            self._pad_buf.extend(chunk)
            self._speech_samples.extend(chunk)

            if prob >= cfg.speech_start_threshold:
                # Speech resumed — go back to SPEECH
                self._state = _STATE_SPEECH
                self._silence_end_frames = 0
                self._pad_buf.clear()
                logger.debug("VAD MAYBE_END->SPEECH (speech resumed) prob=%.3f", prob)
                return None

            if len(self._pad_buf) >= self._pad_samples_needed:
                logger.debug("VAD speech ended, emitting segment")
                return self._emit(doa_angle_deg, force_cut=False)

            return None

        return None

    def _emit(self, doa_angle_deg: float, force_cut: bool) -> AudioSegment:
        arr = np.array(self._speech_samples, dtype=np.float32)
        seg = AudioSegment(
            samples=arr,
            sample_rate=self._sample_rate,
            duration_sec=arr.size / self._sample_rate,
            onset_time=self._onset_time,
            force_cut=force_cut,
            doa_angle_deg=doa_angle_deg,
        )
        self._state = _STATE_SILENCE
        self._speech_samples.clear()
        self._maybe_speech_frames = 0
        self._silence_end_frames = 0
        self._pad_buf.clear()
        if self._model is not None:
            try:
                self._model.reset_states()
            except Exception:
                pass
        logger.info(
            "VAD segment emitted dur=%.2f force_cut=%s",
            seg.duration_sec,
            force_cut,
        )
        return seg
