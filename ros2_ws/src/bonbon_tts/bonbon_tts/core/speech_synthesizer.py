"""
bonbon_tts.core.speech_synthesizer
=====================================
Central orchestrator for the TTS pipeline.

Responsibilities
----------------
- Dequeues utterances from ``UtteranceQueue`` in priority order
- Calls the active TTS backend to synthesise WAV audio
- Hands WAV bytes to the ``AbstractSpeakerBridge`` for playback
- Handles interrupts: stops current playback for EMERGENCY utterances
- Falls back to ``MockTTS`` when the primary backend is unavailable
- Tracks health metrics via ``TTSHealthTracker``
- Optionally triggers filler audio when the queue is deep and the
  pipeline is running slowly

Worker thread
-------------
``start()`` spawns a daemon thread that loops:

    while running:
        utt = queue.dequeue()  or wait
        if utt.interrupt → speaker.stop()
        wav = tts.synthesize(utt.text)
        speaker.play(wav)

The thread sleeps ``_POLL_INTERVAL_SEC`` when the queue is empty.
``wait_until_idle(timeout)`` is provided for test synchronisation.

Shutdown
--------
``stop()`` sets ``_running=False`` and signals the worker event, then
joins the thread with a 5-second timeout.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from bonbon_tts.backends.base_tts import BaseTTS, SynthesisOutput, TTSError
from bonbon_tts.backends.mock_tts import MockTTS
from bonbon_tts.core.tts_health import TTSHealthTracker, TTSHealthReport
from bonbon_tts.core.filler_player import FillerPlayer
from bonbon_tts.core.utterance_queue import UtteranceQueue, Utterance, Priority
from bonbon_tts.speaker.speaker_bridge import AbstractSpeakerBridge

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC = 0.05   # 50 ms idle poll
_WORKER_JOIN_SEC   = 5.0


class SpeechSynthesizer:
    """
    Orchestrates TTS synthesis and audio playback.

    Parameters
    ----------
    primary_tts:
        Primary TTS backend (e.g. ``PiperTTS``).
    speaker:
        Speaker bridge for audio output.
    queue:
        Utterance queue.  A default ``UtteranceQueue(max_depth=32)`` is
        created if not supplied.
    fallback_tts:
        Backend used when *primary_tts* is unavailable.  Defaults to a
        fresh ``MockTTS``.
    filler:
        Filler audio player.  Optional.
    health_tracker:
        Health metric collector.  A default ``TTSHealthTracker()`` is
        created if not supplied.
    """

    def __init__(
        self,
        primary_tts:    BaseTTS,
        speaker:        AbstractSpeakerBridge,
        queue:          Optional[UtteranceQueue]   = None,
        fallback_tts:   Optional[BaseTTS]          = None,
        filler:         Optional[FillerPlayer]     = None,
        health_tracker: Optional[TTSHealthTracker] = None,
    ) -> None:
        self._primary    = primary_tts
        self._fallback   = fallback_tts or MockTTS()
        self._speaker    = speaker
        self._queue      = queue or UtteranceQueue()
        self._filler     = filler
        self._health     = health_tracker or TTSHealthTracker()

        self._running    = False
        self._worker:    Optional[threading.Thread] = None
        self._idle_event = threading.Event()  # set when worker completes an utterance
        self._lock       = threading.Lock()

        # Filler timing
        self._last_play_end_ts: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Warm up backends and start the synthesis worker thread."""
        self._primary.warmup()
        if not self._primary.is_available():
            logger.warning(
                "SpeechSynthesizer: primary backend %r unavailable; "
                "using fallback %r",
                self._primary.backend_name(),
                self._fallback.backend_name(),
            )

        self._fallback.warmup()

        self._running    = True
        self._idle_event.set()  # starts as idle
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="tts-worker",
            daemon=True,
        )
        self._worker.start()
        logger.info("SpeechSynthesizer started (primary=%r fallback=%r)",
                    self._primary.backend_name(), self._fallback.backend_name())

    def stop(self) -> None:
        """Stop the worker thread and release resources."""
        with self._lock:
            self._running = False

        self._speaker.stop()

        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=_WORKER_JOIN_SEC)
            if self._worker.is_alive():
                logger.warning("SpeechSynthesizer: worker thread did not stop cleanly")

        self._primary.shutdown()
        self._fallback.shutdown()
        logger.info("SpeechSynthesizer stopped")

    # ── Enqueueing utterances ──────────────────────────────────────────────────

    def say(self, utt: Utterance) -> bool:
        """
        Enqueue an utterance for synthesis and playback.

        Returns
        -------
        bool
            True if the utterance requires an immediate interrupt.
        """
        interrupt = self._queue.enqueue(utt)
        if interrupt:
            logger.debug("SpeechSynthesizer: interrupt requested for id=%s",
                         utt.utterance_id)
            self._speaker.stop()
        self._idle_event.clear()  # worker has pending work
        return interrupt

    # ── Synchronisation ────────────────────────────────────────────────────────

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        """
        Block until the queue is empty and the worker is idle.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.

        Returns
        -------
        bool
            True if idle was reached within *timeout*, False otherwise.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.is_empty() and self._idle_event.is_set():
                return True
            time.sleep(0.01)
        return False

    # ── Health ─────────────────────────────────────────────────────────────────

    def get_health_report(self) -> TTSHealthReport:
        """Return a health snapshot."""
        backend  = (self._primary.backend_name()
                    if self._primary.is_available()
                    else self._fallback.backend_name())
        synth_ok = self._running
        spkr_ok  = self._speaker.is_available()
        return self._health.get_report(
            queue_depth = self._queue.depth(),
            backend     = backend,
            synth_ok    = synth_ok,
            speaker_ok  = spkr_ok,
        )

    @property
    def queue(self) -> UtteranceQueue:
        return self._queue

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Worker loop ────────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Background synthesis + playback loop."""
        logger.debug("SpeechSynthesizer: worker started")
        while True:
            with self._lock:
                if not self._running:
                    break

            utt = self._queue.dequeue()

            if utt is None:
                # Queue is empty — try filler, then idle
                self._idle_event.set()
                self._maybe_play_filler()
                time.sleep(_POLL_INTERVAL_SEC)
                continue

            self._idle_event.clear()
            self._process_utterance(utt)

        logger.debug("SpeechSynthesizer: worker exited")

    def _process_utterance(self, utt: Utterance) -> None:
        """Synthesise and play a single utterance."""
        # Stop current playback if interrupt is requested
        if utt.interrupt and self._speaker.is_playing():
            self._speaker.stop()

        t0 = time.monotonic()
        output: Optional[SynthesisOutput] = None
        is_fallback = False

        try:
            if self._primary.is_available():
                output = self._primary.synthesize(utt.text)
            else:
                raise TTSError("Primary TTS unavailable", "PRIMARY_UNAVAILABLE")
        except TTSError as exc:
            logger.warning(
                "SpeechSynthesizer: primary TTS failed (id=%s error=%s), "
                "trying fallback",
                utt.utterance_id, exc,
            )
            try:
                output      = self._fallback.synthesize(utt.text)
                is_fallback = True
                output.is_fallback = True
            except TTSError as exc2:
                elapsed_ms = (time.monotonic() - t0) * 1000
                self._health.record_synthesis(elapsed_ms, success=False)
                logger.error(
                    "SpeechSynthesizer: fallback TTS also failed (id=%s): %s",
                    utt.utterance_id, exc2,
                )
                return

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._health.record_synthesis(elapsed_ms, success=True, fallback=is_fallback)

        logger.debug(
            "SpeechSynthesizer: synthesised id=%s backend=%s latency=%.0fms "
            "duration=%.2fs fallback=%s",
            utt.utterance_id,
            output.backend,
            elapsed_ms,
            output.duration_sec,
            is_fallback,
        )

        # Play
        try:
            self._speaker.play(output.wav_bytes)
            self._health.record_play(output.duration_sec)
            self._last_play_end_ts = time.monotonic()
        except Exception as exc:
            logger.error("SpeechSynthesizer: speaker play failed (id=%s): %s",
                         utt.utterance_id, exc)

    def _maybe_play_filler(self) -> None:
        """Trigger filler audio if conditions are met."""
        if self._filler is None or not self._filler.enabled:
            return
        if self._last_play_end_ts == 0.0:
            return

        elapsed_ms = (time.monotonic() - self._last_play_end_ts) * 1000
        self._filler.maybe_play(
            speaker_play_fn = self._speaker.play,
            queue_depth     = self._queue.depth(),
            elapsed_ms      = elapsed_ms,
        )
