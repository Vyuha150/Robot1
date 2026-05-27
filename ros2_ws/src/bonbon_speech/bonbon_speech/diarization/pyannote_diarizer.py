"""
bonbon_speech.diarization.pyannote_diarizer
=============================================
pyannote.audio speaker diarization backend.

Requirements:
  * ``pip install pyannote.audio``
  * A HuggingFace access token with acceptance of the pyannote model EULA.
    Token injected via ROS2 param ``diarization_hf_token`` — NEVER hardcoded.

The backend wraps pyannote's ``Pipeline`` in a ThreadPoolExecutor future so
the inference_timeout_sec cap from DiarizationConfig is honoured.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import numpy as np

from bonbon_speech.config.speech_config import DiarizationConfig
from bonbon_speech.diarization.base_diarizer import (
    BaseDiarizer,
    DiarizationResult,
    SpeakerSegment,
)

logger = logging.getLogger(__name__)


class PyAnnoteDiarizer(BaseDiarizer):
    """pyannote.audio diarization with timeout guard."""

    def __init__(self, cfg: DiarizationConfig) -> None:
        super().__init__(cfg)
        self._pipeline = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="diarize")

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._pipeline is not None:
            return  # idempotent

        cfg = self._cfg
        if not cfg.hf_token:
            logger.warning(
                "PyAnnoteDiarizer: hf_token is empty — pipeline load may fail. "
                "Set diarization_hf_token ROS2 parameter."
            )

        try:
            from pyannote.audio import Pipeline  # type: ignore

            if cfg.pipeline_path:
                logger.info("PyAnnoteDiarizer loading from path=%s", cfg.pipeline_path)
                self._pipeline = Pipeline.from_pretrained(
                    cfg.pipeline_path,
                    use_auth_token=cfg.hf_token or None,
                )
            else:
                logger.info("PyAnnoteDiarizer loading from HuggingFace hub …")
                self._pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=cfg.hf_token or None,
                )

            logger.info("PyAnnoteDiarizer pipeline loaded ok")
        except Exception as exc:
            logger.error("PyAnnoteDiarizer load failed: %s", exc)
            raise

    def unload(self) -> None:
        self._pipeline = None
        logger.debug("PyAnnoteDiarizer unloaded")

    # ── Diarization ──────────────────────────────────────────────────────────

    def diarize(
        self,
        samples: np.ndarray,
        sample_rate: int = 16000,
    ) -> DiarizationResult:
        if self._pipeline is None:
            logger.error("PyAnnoteDiarizer.load() not called")
            return DiarizationResult()

        cfg = self._cfg
        t0 = time.monotonic()

        future = self._executor.submit(self._run_pipeline, samples, sample_rate, cfg)
        try:
            result = future.result(timeout=cfg.inference_timeout_sec)
            elapsed = (time.monotonic() - t0) * 1000.0
            logger.debug(
                "PyAnnoteDiarizer done n_speakers=%d ms=%.1f",
                len(result.all_speaker_ids),
                elapsed,
            )
            return result
        except FutureTimeout:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.warning(
                "PyAnnoteDiarizer timeout after %.0fms (limit=%ds)",
                elapsed_ms,
                cfg.inference_timeout_sec,
            )
            return DiarizationResult(is_timeout=True)
        except Exception as exc:
            logger.error("PyAnnoteDiarizer exception: %s", exc)
            return DiarizationResult()

    def _run_pipeline(
        self,
        samples: np.ndarray,
        sample_rate: int,
        cfg: DiarizationConfig,
    ) -> DiarizationResult:
        """Worker: calls pyannote inside the executor thread."""
        import torch

        # pyannote wants a dict with 'waveform' (C, T) tensor and 'sample_rate'
        waveform = torch.from_numpy(samples.astype(np.float32)).unsqueeze(0)
        audio = {"waveform": waveform, "sample_rate": sample_rate}

        kwargs = {}
        if cfg.min_speakers > 1:
            kwargs["min_speakers"] = cfg.min_speakers
        if cfg.max_speakers:
            kwargs["max_speakers"] = cfg.max_speakers

        diarization = self._pipeline(audio, **kwargs)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                SpeakerSegment(
                    speaker_id=speaker,
                    start_sec=float(turn.start),
                    end_sec=float(turn.end),
                    confidence=1.0,
                )
            )

        return DiarizationResult(segments=segments)
