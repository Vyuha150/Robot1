"""
bonbon_tts.core.filler_player
===============================
Filler audio manager — plays short bridging clips ("one moment please",
"let me think") while the LLM or TTS pipeline is working.

Design goals
------------
- Zero external dependencies: falls back to synthesised beep WAVs when
  no real clip files are present.
- Cooldown: avoids playing filler clips too frequently.
- Pluggable clip loading: discovers WAV files in ``filler_dir`` or uses
  hardcoded built-in clips.

Clip selection
--------------
Clips are chosen randomly (``random.choice``) on each ``play_random()``
call, with cooldown enforcement.

``maybe_play()``
----------------
Called by SpeechSynthesizer when queue depth exceeds the trigger threshold.
Only plays if the cooldown has elapsed since the last filler play.
"""

from __future__ import annotations

import logging
import os
import random
import time

logger = logging.getLogger(__name__)


# ── FillerClip ────────────────────────────────────────────────────────────────


class FillerClip:
    """A single filler audio clip held in memory."""

    def __init__(self, name: str, wav_bytes: bytes) -> None:
        self.name = name
        self.wav_bytes = wav_bytes

    def __repr__(self) -> str:
        return f"FillerClip(name={self.name!r}, size={len(self.wav_bytes)})"


# ── FillerPlayer ─────────────────────────────────────────────────────────────


class FillerPlayer:
    """
    Loads and plays short bridging audio clips.

    Parameters
    ----------
    filler_dir:
        Directory containing ``*.wav`` filler clips.  If empty or the
        directory is absent, ``generate_builtin()`` is called instead.
    cooldown_sec:
        Minimum seconds between two filler plays.
    trigger_queue_depth:
        Minimum queue depth that enables filler playback.
    trigger_latency_ms:
        How long (ms) the pipeline must have been silent before filler
        is eligible (prevents filler playing when speech is near-instant).
    enabled:
        Master switch — ``maybe_play`` is a no-op when False.
    """

    def __init__(
        self,
        filler_dir: str = "",
        cooldown_sec: float = 3.0,
        trigger_queue_depth: int = 2,
        trigger_latency_ms: float = 400.0,
        enabled: bool = True,
    ) -> None:
        self._filler_dir = filler_dir
        self._cooldown_sec = cooldown_sec
        self._trigger_queue_depth = trigger_queue_depth
        self._trigger_latency_ms = trigger_latency_ms
        self._enabled = enabled

        self._clips: list[FillerClip] = []
        self._last_played_ts: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def load(self) -> int:
        """
        Discover and load filler clips.

        Tries to load WAV files from ``filler_dir`` first.  Falls back to
        ``generate_builtin()`` if none are found.

        Returns
        -------
        int
            Number of clips loaded.
        """
        if self._filler_dir and os.path.isdir(self._filler_dir):
            self._clips = self._load_from_dir(self._filler_dir)
            if self._clips:
                logger.info(
                    "FillerPlayer: loaded %d clips from %r", len(self._clips), self._filler_dir
                )
                return len(self._clips)

        logger.info("FillerPlayer: no clip dir found, generating built-in clips")
        self._clips = self.generate_builtin()
        return len(self._clips)

    # ── Public API ─────────────────────────────────────────────────────────────

    def maybe_play(
        self,
        speaker_play_fn,
        queue_depth: int,
        elapsed_ms: float,
    ) -> bool:
        """
        Conditionally play a filler clip.

        Parameters
        ----------
        speaker_play_fn:
            Callable ``(wav_bytes: bytes) -> None`` that plays audio.
        queue_depth:
            Current utterance queue depth.
        elapsed_ms:
            How long (ms) since the last utterance finished playing.

        Returns
        -------
        bool
            True if a filler clip was played.
        """
        if not self._enabled:
            return False
        if not self._clips:
            return False
        if queue_depth < self._trigger_queue_depth:
            return False
        if elapsed_ms < self._trigger_latency_ms:
            return False
        now = time.monotonic()
        if (now - self._last_played_ts) < self._cooldown_sec:
            return False

        clip = random.choice(self._clips)
        try:
            speaker_play_fn(clip.wav_bytes)
            self._last_played_ts = time.monotonic()
            logger.debug("FillerPlayer: played %r", clip.name)
            return True
        except Exception as exc:
            logger.warning("FillerPlayer: play failed: %s", exc)
            return False

    def play_random(self, speaker_play_fn) -> bool:
        """
        Play a random clip unconditionally (ignores cooldown).

        Useful for manual triggers or tests.
        """
        if not self._clips:
            return False
        clip = random.choice(self._clips)
        try:
            speaker_play_fn(clip.wav_bytes)
            self._last_played_ts = time.monotonic()
            return True
        except Exception as exc:
            logger.warning("FillerPlayer: play_random failed: %s", exc)
            return False

    @property
    def clip_count(self) -> int:
        """Number of loaded clips."""
        return len(self._clips)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # ── Built-in clip generation ───────────────────────────────────────────────

    @staticmethod
    def generate_builtin() -> list[FillerClip]:
        """
        Generate minimal built-in filler clips using pure-Python WAV synthesis.

        Returns three clips:
        - "thinking"    — descending two-tone chord (indicates processing)
        - "one_moment"  — soft single tone
        - "please_wait" — rising two-tone

        All produced with only stdlib ``wave``, ``math``, ``struct``.
        """
        from bonbon_tts.backends.mock_tts import generate_beep_wav

        clips = []

        # "thinking" — 440 Hz + short silence (0.25 s total)
        beep1 = generate_beep_wav(
            duration_sec=0.12, freq_hz=440.0, sample_rate=22050, amplitude=0.18
        )
        clips.append(FillerClip("thinking", beep1))

        # "one_moment" — 523 Hz (C5) soft tone
        beep2 = generate_beep_wav(
            duration_sec=0.10, freq_hz=523.0, sample_rate=22050, amplitude=0.15
        )
        clips.append(FillerClip("one_moment", beep2))

        # "please_wait" — 660 Hz brief tone
        beep3 = generate_beep_wav(
            duration_sec=0.08, freq_hz=660.0, sample_rate=22050, amplitude=0.15
        )
        clips.append(FillerClip("please_wait", beep3))

        return clips

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _load_from_dir(directory: str) -> list[FillerClip]:
        """Load all WAV files from *directory* into memory."""
        clips: list[FillerClip] = []
        try:
            entries = sorted(os.listdir(directory))
        except OSError as exc:
            logger.warning("FillerPlayer: cannot list dir %r: %s", directory, exc)
            return clips

        for fname in entries:
            if not fname.lower().endswith(".wav"):
                continue
            path = os.path.join(directory, fname)
            try:
                with open(path, "rb") as fh:
                    wav_bytes = fh.read()
                clips.append(FillerClip(name=os.path.splitext(fname)[0], wav_bytes=wav_bytes))
            except OSError as exc:
                logger.warning("FillerPlayer: cannot read %r: %s", path, exc)

        return clips
