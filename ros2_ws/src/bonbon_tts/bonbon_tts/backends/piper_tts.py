"""
bonbon_tts.backends.piper_tts
================================
Piper neural TTS backend.

Piper (https://github.com/rhasspy/piper) is a fast, offline neural
text-to-speech engine designed for embedded devices.

Two operating modes
-------------------
1. **Subprocess mode** (default, ``use_subprocess=True``):
   Spawns a ``piper`` process per utterance.  Isolated memory, easy to
   restart, works with any Piper build.

   Command used::

       echo "Hello" | piper \\
           --model /path/to/model.onnx \\
           --output_file /tmp/tts_xyz.wav

2. **Python API mode** (``use_subprocess=False``):
   Uses the ``piper_tts`` Python package directly.  Lower latency
   (~50 ms vs. ~150 ms), but loads the model into the ROS2 process.

Availability
------------
PiperTTS.is_available() returns False if:
  - The model file does not exist, AND
  - The piper executable is not on PATH (subprocess mode) or
    the piper_tts package is not installed (API mode).

On unavailability the SpeechSynthesizer falls back to MockTTS.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from typing import Optional

from bonbon_tts.backends.base_tts import BaseTTS, SynthesisOutput, TTSError
from bonbon_tts.config.tts_config import PiperConfig

logger = logging.getLogger(__name__)


class PiperTTS(BaseTTS):
    """
    Piper TTS backend.

    Parameters
    ----------
    cfg : PiperConfig
        Runtime configuration (model path, voice, rate, etc.)
    """

    def __init__(self, cfg: PiperConfig) -> None:
        self._cfg   = cfg
        self._lock  = threading.Lock()
        self._ready = False

        # Python API handle (set during warmup when use_subprocess=False)
        self._voice = None

    # ── BaseTTS interface ──────────────────────────────────────────────────────

    def warmup(self) -> None:
        """Load models or verify subprocess availability."""
        if self._cfg.use_subprocess:
            self._warmup_subprocess()
        else:
            self._warmup_api()

    def is_available(self) -> bool:
        return self._ready

    def synthesize(self, text: str) -> SynthesisOutput:
        if not self._ready:
            raise TTSError("Piper TTS is not available", "PIPER_NOT_READY")

        t0 = time.monotonic()
        try:
            if self._cfg.use_subprocess:
                output = self._synthesize_subprocess(text)
            else:
                output = self._synthesize_api(text)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"Piper synthesis error: {exc}", "PIPER_ERROR") from exc

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug("Piper synthesised %d chars in %.0f ms", len(text), elapsed_ms)
        return output

    def shutdown(self) -> None:
        self._ready = False
        self._voice = None
        logger.info("PiperTTS shut down")

    def backend_name(self) -> str:
        return "piper"

    # ── Subprocess mode ────────────────────────────────────────────────────────

    def _warmup_subprocess(self) -> None:
        exe = self._cfg.executable or "piper"
        if not shutil.which(exe):
            logger.warning(
                "Piper executable %r not found on PATH. TTS will use fallback.", exe
            )
            self._ready = False
            return

        if self._cfg.model_path and not os.path.isfile(self._cfg.model_path):
            logger.warning(
                "Piper model file not found: %r. TTS will use fallback.",
                self._cfg.model_path,
            )
            self._ready = False
            return

        self._ready = True
        logger.info("PiperTTS (subprocess) ready: exe=%r model=%r",
                    exe, self._cfg.model_path or "default voice")

    def _synthesize_subprocess(self, text: str) -> SynthesisOutput:
        exe = self._cfg.executable or "piper"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            out_path = tf.name

        try:
            cmd = [exe, "--output_file", out_path]

            if self._cfg.model_path:
                cmd += ["--model", self._cfg.model_path]
            else:
                cmd += ["--model", self._cfg.voice]

            if self._cfg.config_path:
                cmd += ["--config", self._cfg.config_path]

            if self._cfg.length_scale != 1.0:
                cmd += ["--length_scale", str(self._cfg.length_scale)]
            if self._cfg.noise_scale != 0.667:
                cmd += ["--noise_scale", str(self._cfg.noise_scale)]
            if self._cfg.noise_w != 0.8:
                cmd += ["--noise_w", str(self._cfg.noise_w)]
            if self._cfg.sentence_silence_sec != 0.2:
                cmd += ["--sentence_silence", str(self._cfg.sentence_silence_sec)]
            if self._cfg.cuda:
                cmd += ["--cuda"]

            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=self._cfg.synthesis_timeout_sec,
            )

            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                raise TTSError(
                    f"Piper exited {proc.returncode}: {stderr}",
                    "PIPER_NONZERO_EXIT",
                )

            if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                raise TTSError("Piper produced no output file", "PIPER_EMPTY_OUTPUT")

            return self._read_wav_file(out_path, text)

        except subprocess.TimeoutExpired:
            raise TTSError(
                f"Piper subprocess timed out ({self._cfg.synthesis_timeout_sec}s)",
                "PIPER_TIMEOUT",
            )
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    # ── Python API mode ────────────────────────────────────────────────────────

    def _warmup_api(self) -> None:
        try:
            from piper.voice import PiperVoice  # type: ignore[import]
        except ImportError:
            logger.warning(
                "piper_tts Python package not installed. TTS will use fallback."
            )
            self._ready = False
            return

        if not self._cfg.model_path or not os.path.isfile(self._cfg.model_path):
            logger.warning(
                "Piper model file not found: %r. TTS will use fallback.",
                self._cfg.model_path,
            )
            self._ready = False
            return

        try:
            self._voice = PiperVoice.load(
                self._cfg.model_path,
                config_path=self._cfg.config_path or None,
                use_cuda=self._cfg.cuda,
            )
            self._ready = True
            logger.info("PiperTTS (API) ready: model=%r", self._cfg.model_path)
        except Exception as exc:
            logger.warning("PiperTTS API warmup failed: %s", exc)
            self._ready = False

    def _synthesize_api(self, text: str) -> SynthesisOutput:
        if self._voice is None:
            raise TTSError("PiperVoice not loaded", "PIPER_NOT_LOADED")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            out_path = tf.name

        try:
            with wave.open(out_path, "wb") as wav_file:
                with self._lock:
                    self._voice.synthesize(text, wav_file)

            return self._read_wav_file(out_path, text)
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    # ── WAV reading ────────────────────────────────────────────────────────────

    @staticmethod
    def _read_wav_file(path: str, text: str) -> SynthesisOutput:
        """Read a WAV file and return SynthesisOutput."""
        with wave.open(path, "rb") as wf:
            sample_rate  = wf.getframerate()
            n_frames     = wf.getnframes()
            duration_sec = n_frames / sample_rate

        with open(path, "rb") as fh:
            wav_bytes = fh.read()

        return SynthesisOutput(
            wav_bytes    = wav_bytes,
            duration_sec = duration_sec,
            text         = text,
            sample_rate  = sample_rate,
            backend      = "piper",
        )
