"""
bonbon_speech.stt.whisper_stt
==============================
OpenAI Whisper STT backend.

Supports both ``whisper`` (openai-whisper) and ``faster_whisper``
(CTranslate2-based, faster on CPU) depending on STTConfig.backend.

Confidence: Whisper exposes ``avg_logprob`` per segment — we convert it to
[0,1] via sigmoid-like scaling so downstream code gets a normalised score.

avg_logprob ranges from roughly -3.0 (confident) to very negative (noise).
Mapping:  conf = exp(avg_logprob) but clamped to [0, 1].
"""

from __future__ import annotations

import logging
import math
import os

import numpy as np

from bonbon_speech.config.speech_config import STTConfig
from bonbon_speech.stt.base_stt import BaseSTT, TranscriptionResult

logger = logging.getLogger(__name__)


def _logprob_to_conf(avg_logprob: float) -> float:
    """Convert Whisper avg_logprob to a [0, 1] confidence score."""
    # exp(0) = 1.0 (perfect), exp(-inf) = 0.0 (no signal)
    return float(min(1.0, max(0.0, math.exp(avg_logprob))))


class WhisperSTT(BaseSTT):
    """OpenAI Whisper backend (``whisper`` or ``faster_whisper``)."""

    def __init__(self, cfg: STTConfig) -> None:
        super().__init__(cfg)
        self._model = None
        self._backend = cfg.backend  # "whisper" | "faster_whisper"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._model is not None:
            return  # idempotent

        cfg = self._cfg
        logger.info(
            "WhisperSTT loading backend=%s model=%s device=%s",
            cfg.backend,
            cfg.model_size,
            cfg.device or "auto",
        )

        if cfg.backend == "faster_whisper":
            from faster_whisper import WhisperModel  # type: ignore

            device = cfg.device or "auto"
            compute = "float32" if device == "cpu" else "float16"
            model_path = cfg.model_dir if cfg.model_dir else cfg.model_size
            self._model = WhisperModel(
                model_path,
                device=device,
                compute_type=compute,
                download_root=cfg.model_dir or None,
            )
        else:  # "whisper"
            import whisper  # type: ignore

            model_path = (
                os.path.join(cfg.model_dir, cfg.model_size) if cfg.model_dir else cfg.model_size
            )
            device = cfg.device or None
            self._model = whisper.load_model(model_path, device=device)

        self.reset_degraded()
        logger.info("WhisperSTT model loaded ok")

    def unload(self) -> None:
        self._model = None
        self.reset_degraded()
        logger.debug("WhisperSTT unloaded")

    # ── Inference ────────────────────────────────────────────────────────────

    def _transcribe_impl(
        self,
        samples: np.ndarray,
        sample_rate: int,
    ) -> TranscriptionResult:
        cfg = self._cfg
        samples_f32 = samples.astype(np.float32)

        # Resample to 16 kHz if needed (Whisper requirement)
        if sample_rate != 16000:
            samples_f32 = _resample(samples_f32, sample_rate, 16000)

        if cfg.backend == "faster_whisper":
            return self._run_faster_whisper(samples_f32, cfg)
        else:
            return self._run_whisper(samples_f32, cfg)

    def _run_whisper(self, samples: np.ndarray, cfg: STTConfig) -> TranscriptionResult:

        opts: dict = {
            "language": cfg.language or None,
            "task": cfg.task,
            "beam_size": cfg.beam_size,
            "best_of": cfg.best_of,
            "temperature": cfg.temperature,
            "word_timestamps": cfg.word_timestamps,
            "suppress_tokens": cfg.suppress_tokens,
            "verbose": False,
        }
        raw = self._model.transcribe(samples, **opts)

        # Aggregate confidence from segments
        segs = raw.get("segments", [])
        if segs:
            avg_lp = sum(s.get("avg_logprob", -1.0) for s in segs) / len(segs)
        else:
            avg_lp = -1.0
        conf = _logprob_to_conf(avg_lp)

        result = TranscriptionResult(
            text=raw.get("text", "").strip(),
            language=raw.get("language", ""),
            confidence=conf,
        )

        if cfg.word_timestamps:
            for seg in segs:
                for w in seg.get("words", []):
                    result.words.append(w.get("word", "").strip())
                    result.word_start_times_sec.append(float(w.get("start", 0.0)))
                    result.word_end_times_sec.append(float(w.get("end", 0.0)))
                    result.word_confidences.append(_logprob_to_conf(w.get("probability", 0.5)))

        return result

    def _run_faster_whisper(self, samples: np.ndarray, cfg: STTConfig) -> TranscriptionResult:
        segs_gen, info = self._model.transcribe(
            samples,
            language=cfg.language or None,
            task=cfg.task,
            beam_size=cfg.beam_size,
            best_of=cfg.best_of,
            temperature=cfg.temperature,
            word_timestamps=cfg.word_timestamps,
            suppress_tokens=[int(t) for t in cfg.suppress_tokens.split(",") if t.strip()],
        )

        texts = []
        log_probs = []
        words_list = []
        word_starts = []
        word_ends = []
        word_confs = []

        for seg in segs_gen:
            texts.append(seg.text.strip())
            log_probs.append(seg.avg_logprob)
            if cfg.word_timestamps and seg.words:
                for w in seg.words:
                    words_list.append(w.word.strip())
                    word_starts.append(float(w.start))
                    word_ends.append(float(w.end))
                    word_confs.append(float(w.probability))

        avg_lp = sum(log_probs) / len(log_probs) if log_probs else -1.0
        conf = _logprob_to_conf(avg_lp)

        return TranscriptionResult(
            text=" ".join(texts).strip(),
            language=info.language,
            confidence=conf,
            words=words_list,
            word_start_times_sec=word_starts,
            word_end_times_sec=word_ends,
            word_confidences=word_confs,
        )


# ── Helper ────────────────────────────────────────────────────────────────────


def _resample(samples: np.ndarray, from_hz: int, to_hz: int) -> np.ndarray:
    """Naive linear-interpolation resample (fallback, no scipy dependency)."""
    if from_hz == to_hz:
        return samples
    ratio = to_hz / from_hz
    n_out = int(len(samples) * ratio)
    x_old = np.linspace(0, 1, len(samples))
    x_new = np.linspace(0, 1, n_out)
    return np.interp(x_new, x_old, samples).astype(np.float32)
