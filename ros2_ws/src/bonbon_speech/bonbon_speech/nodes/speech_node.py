"""
bonbon_speech.nodes.speech_node
================================
ROS2 LifecycleNode for the full speech recognition pipeline.

Pipeline
--------
AudioChunk (HAL) --> AudioPreprocessor --> [WakeWordDetector] -->
AudioBuffer --> SileroVAD --> WhisperSTT --> [PyAnnoteDiarizer] -->
SpeechCommand + SpeechTranscription (ROS2 topics) --> SafetySupervisor

Lifecycle states
----------------
unconfigured  → on_configure  → inactive
inactive      → on_activate   → active  (pipeline starts)
active        → on_deactivate → inactive
inactive      → on_cleanup    → unconfigured
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

# ── ROS2 imports (stubbed in tests via sys.modules injection) ─────────────────
import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

logger = logging.getLogger(__name__)


class SpeechNode(LifecycleNode):
    """
    Full speech recognition pipeline as a managed LifecycleNode.

    Topics published
    ----------------
    /speech/command        bonbon_msgs/SpeechCommand
    /speech/transcription  bonbon_msgs/SpeechTranscription
    /health/speech         bonbon_msgs/ModuleHealth

    Topics subscribed
    -----------------
    /hal/audio             bonbon_msgs/AudioChunk
    """

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self, node_name: str = "speech_node") -> None:
        super().__init__(node_name)

        # Declared at configure time
        self._cfg = None
        self._buf = None
        self._preproc = None
        self._vad = None
        self._stt = None
        self._diarizer = None
        self._ww = None

        # Publishers / subscribers — created at configure
        self._pub_command = None
        self._pub_transcription = None
        self._pub_health = None
        self._sub_audio = None

        # Health
        self._health_timer = None
        self._pipeline_ok = False
        self._error_msg = ""

        # Wake-word state
        self._ww_armed: bool = True  # True = accepting wake words
        self._ww_listen_deadline: float = 0.0

        # Thread lock for VAD state
        self._vad_lock = threading.Lock()

        self.get_logger().info("SpeechNode created")

    # ── Lifecycle: configure ──────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_configure")
        try:
            self._load_config()
            self._create_interfaces()
            self._init_pipeline()
            self._pipeline_ok = True
            self.get_logger().info("configured ok summary=%s", self._cfg.summary())
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f"configure failed: {exc}")
            self._error_msg = str(exc)
            if self._cfg and self._cfg.allow_degraded_startup:
                self.get_logger().warning("allow_degraded=True — continuing in degraded mode")
                return TransitionCallbackReturn.SUCCESS
            return TransitionCallbackReturn.FAILURE

    def _load_config(self) -> None:
        from bonbon_speech.config.speech_config import SpeechConfig

        self._cfg = SpeechConfig.from_ros_params(self)
        self._cfg.validate()

    def _create_interfaces(self) -> None:
        from bonbon_msgs.msg import (  # type: ignore
            AudioChunk,
            ModuleHealth,  # type: ignore
            SpeechCommand,
            SpeechTranscription,
        )

        best_effort_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self._pub_command = self.create_lifecycle_publisher(
            SpeechCommand, "/speech/command", reliable_qos
        )
        self._pub_transcription = self.create_lifecycle_publisher(
            SpeechTranscription, "/speech/transcription", reliable_qos
        )
        self._pub_health = self.create_lifecycle_publisher(
            ModuleHealth, "/health/speech", reliable_qos
        )
        self._sub_audio = self.create_subscription(
            AudioChunk, "/bonbon/speech/audio", self._on_audio_chunk, best_effort_qos
        )

    def _init_pipeline(self) -> None:
        cfg = self._cfg

        # Audio buffer
        from bonbon_speech.audio.audio_buffer import AudioBuffer

        self._buf = AudioBuffer(
            sample_rate=cfg.audio.sample_rate,
            max_buffer_sec=cfg.audio.max_buffer_sec,
            prebuffer_sec=cfg.audio.prebuffer_sec,
        )

        # Preprocessor
        from bonbon_speech.audio.audio_preprocessor import (
            AudioPreprocessor,
            PreprocessorConfig,
        )

        self._preproc = AudioPreprocessor(PreprocessorConfig())

        # VAD
        self._vad = self._make_vad(cfg)
        try:
            self._vad.load()
        except Exception as exc:
            self.get_logger().error(f"VAD load failed: {exc}")
            if not cfg.allow_degraded_startup:
                raise
            self._pipeline_ok = False
            self._error_msg = f"VAD load failed: {exc}"

        # STT
        self._stt = self._make_stt(cfg)
        try:
            self._stt.load()
        except Exception as exc:
            self.get_logger().error(f"STT load failed: {exc}")
            if not cfg.allow_degraded_startup:
                raise
            self._pipeline_ok = False
            self._error_msg = f"STT load failed: {exc}"

        # Diarization (optional)
        if cfg.diarization.enabled:
            self._diarizer = self._make_diarizer(cfg)
            try:
                self._diarizer.load()
            except Exception as exc:
                self.get_logger().warning(f"Diarizer load failed (non-fatal): {exc}")
                self._diarizer = None

        # Wake word (optional)
        if cfg.wake_word.enabled:
            self._ww = self._make_wake_word(cfg)
            try:
                self._ww.load()
            except Exception as exc:
                self.get_logger().warning(f"Wake word load failed (non-fatal): {exc}")
                self._ww = None

    def _make_vad(self, cfg):
        if cfg.vad.backend == "silero":
            from bonbon_speech.vad.silero_vad import SileroVAD

            return SileroVAD(cfg.vad, cfg.audio.sample_rate)
        else:
            from bonbon_speech.vad.mock_vad import MockVAD

            return MockVAD(cfg.audio.sample_rate)

    def _make_stt(self, cfg):
        if cfg.stt.backend in ("whisper", "faster_whisper"):
            from bonbon_speech.stt.whisper_stt import WhisperSTT

            return WhisperSTT(cfg.stt)
        else:
            from bonbon_speech.stt.mock_stt import MockSTT

            return MockSTT(cfg.stt)

    def _make_diarizer(self, cfg):
        if cfg.diarization.backend == "pyannote":
            from bonbon_speech.diarization.pyannote_diarizer import PyAnnoteDiarizer

            return PyAnnoteDiarizer(cfg.diarization)
        else:
            from bonbon_speech.diarization.mock_diarizer import MockDiarizer

            return MockDiarizer(cfg.diarization)

    def _make_wake_word(self, cfg):
        from bonbon_speech.wake_word.wake_word_detector import make_wake_word_detector

        return make_wake_word_detector(cfg.wake_word)

    # ── Lifecycle: activate / deactivate / cleanup ────────────────────────────

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_activate")
        self._health_timer = self.create_timer(
            1.0 / self._cfg.health_rate_hz,
            self._publish_health,
        )
        self._ww_armed = True
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_deactivate")
        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
        if self._buf:
            self._buf.clear()
        if self._vad:
            with self._vad_lock:
                self._vad.reset()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_cleanup")
        self._teardown_pipeline()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_shutdown")
        self._teardown_pipeline()
        return TransitionCallbackReturn.SUCCESS

    def _teardown_pipeline(self) -> None:
        for component, name in [
            (self._vad, "VAD"),
            (self._stt, "STT"),
            (self._diarizer, "Diarizer"),
            (self._ww, "WakeWord"),
        ]:
            if component is not None:
                try:
                    component.unload()
                except Exception as exc:
                    self.get_logger().warning(f"{name} unload error: {exc}")
        if self._buf:
            self._buf.clear()

    # ── Audio callback ────────────────────────────────────────────────────────

    def _on_audio_chunk(self, msg) -> None:
        """
        Main hot path: called for every AudioChunk published by the HAL mic.

        Steps
        -----
        1. Convert msg.data → float32 numpy array.
        2. Preprocess (DC removal, normalisation).
        3. [Optional] Wake-word gate.
        4. Push to AudioBuffer.
        5. Feed to VAD state machine.
        6. If VAD emits a segment → run STT (+ diarization).
        7. Build and publish SpeechCommand (+ SpeechTranscription).
        """
        try:
            samples = np.array(msg.data, dtype=np.float32)
        except Exception as exc:
            self.get_logger().warning(f"Audio decode error: {exc}")
            return

        # Preprocess
        samples = self._preproc.process(samples)

        doa = float(getattr(msg, "doa_angle_deg", 0.0))

        # Wake-word gate (only when enabled)
        if self._cfg.wake_word.enabled and self._ww is not None:
            if self._ww_armed:
                detected, score = self._ww.process_chunk(samples)
                if detected:
                    self.get_logger().info(
                        "wake_word detected keyword=%r score=%.3f",
                        self._cfg.wake_word.keyword,
                        score,
                    )
                    self._ww_armed = False
                    self._ww_listen_deadline = (
                        time.monotonic() + self._cfg.wake_word.listen_timeout_sec
                    )
                    with self._vad_lock:
                        self._vad.reset()
                    self._buf.clear()
                else:
                    return  # not armed for speech yet
            else:
                # Listening window — re-arm if timed out
                if time.monotonic() > self._ww_listen_deadline:
                    self._ww_armed = True
                    with self._vad_lock:
                        self._vad.reset()
                    self._buf.clear()
                    return

        # Push to buffer
        self._buf.push(samples)

        # VAD
        with self._vad_lock:
            segment = self._vad.process_chunk(samples, doa_angle_deg=doa)

        if segment is None:
            return

        # Re-arm wake word after utterance
        if self._cfg.wake_word.enabled:
            self._ww_armed = True

        self._process_segment(
            segment, msg.header, wake_word_triggered=(self._cfg.wake_word.enabled)  # was gated
        )

    # ── Segment processing ────────────────────────────────────────────────────

    def _process_segment(self, segment, header, wake_word_triggered: bool) -> None:
        """Run STT + optional diarization; publish results."""
        t0 = time.monotonic()

        # Silence / empty check
        if segment.samples.size == 0:
            self._publish_silence(header)
            return

        # STT
        stt_result = self._stt.transcribe(segment.samples, segment.sample_rate)

        transcription_ms = (time.monotonic() - t0) * 1000.0
        stt_result.inference_ms = transcription_ms

        # Diarization (optional)
        speaker_id = "SPEAKER_00"
        all_speakers = ["SPEAKER_00"]
        if self._diarizer is not None:
            diar = self._diarizer.diarize(segment.samples, segment.sample_rate)
            if not diar.is_timeout:
                speaker_id = diar.dominant_speaker
                all_speakers = diar.all_speaker_ids

        # Privacy: anonymise speaker if required
        if self._cfg.privacy.anonymize_speaker:
            speaker_id = "SPEAKER_ANON"
            all_speakers = ["SPEAKER_ANON"]

        # Build and publish messages
        self._publish_command(
            header=header,
            stt=stt_result,
            speaker_id=speaker_id,
            duration_sec=segment.duration_sec,
            transcription_ms=transcription_ms,
            doa=segment.doa_angle_deg,
            wake_word_triggered=wake_word_triggered,
            force_cut=segment.force_cut,
        )

        if self._cfg.publish_transcription_detail:
            self._publish_transcription(
                header=header,
                stt=stt_result,
                speaker_id=speaker_id,
                all_speakers=all_speakers,
                duration_sec=segment.duration_sec,
                transcription_ms=transcription_ms,
                doa=segment.doa_angle_deg,
                force_cut=segment.force_cut,
            )

    # ── Publishers ────────────────────────────────────────────────────────────

    def _publish_command(
        self,
        header,
        stt,
        speaker_id: str,
        duration_sec: float,
        transcription_ms: float,
        doa: float,
        wake_word_triggered: bool,
        force_cut: bool,
    ) -> None:
        from bonbon_msgs.msg import SpeechCommand  # type: ignore

        msg = SpeechCommand()
        msg.header = header
        msg.text = stt.text
        msg.language = stt.language
        msg.confidence = float(stt.confidence)
        msg.is_low_confidence = stt.is_low_confidence
        msg.is_timeout = stt.is_timeout
        msg.is_silence = stt.is_silence
        msg.wake_word_triggered = wake_word_triggered
        msg.speaker_id = speaker_id
        msg.audio_duration_sec = float(duration_sec)
        msg.transcription_ms = float(transcription_ms)
        msg.doa_angle_deg = float(doa)
        self._pub_command.publish(msg)
        self.get_logger().debug(
            "published SpeechCommand text=%r conf=%.3f lang=%r speaker=%s",
            msg.text[:60],
            msg.confidence,
            msg.language,
            speaker_id,
        )

    def _publish_transcription(
        self,
        header,
        stt,
        speaker_id: str,
        all_speakers,
        duration_sec: float,
        transcription_ms: float,
        doa: float,
        force_cut: bool,
    ) -> None:
        from bonbon_msgs.msg import SpeechTranscription  # type: ignore

        msg = SpeechTranscription()
        msg.header = header
        msg.text = stt.text
        msg.language = stt.language
        msg.confidence = float(stt.confidence)
        msg.words = list(stt.words)
        msg.word_start_times_sec = [float(t) for t in stt.word_start_times_sec]
        msg.word_end_times_sec = [float(t) for t in stt.word_end_times_sec]
        msg.word_confidences = [float(c) for c in stt.word_confidences]
        msg.speaker_id = speaker_id
        msg.all_speaker_ids = list(all_speakers)
        msg.audio_duration_sec = float(duration_sec)
        msg.transcription_ms = float(transcription_ms)
        msg.doa_angle_deg = float(doa)
        msg.vad_force_cut = force_cut
        self._pub_transcription.publish(msg)

    def _publish_silence(self, header) -> None:
        from bonbon_msgs.msg import SpeechCommand  # type: ignore

        msg = SpeechCommand()
        msg.header = header
        msg.is_silence = True
        msg.text = ""
        self._pub_command.publish(msg)

    # ── Constants mirroring ModuleHealth.msg ─────────────────────────────────
    _HEALTH_OK = 0
    _HEALTH_WARN = 1
    _HEALTH_ERROR = 2

    def _publish_health(self) -> None:
        try:
            from bonbon_msgs.msg import ModuleHealth  # type: ignore

            stt_degraded = self._stt.is_degraded if self._stt else False
            overall_ok = self._pipeline_ok and not stt_degraded

            msg = ModuleHealth()
            msg.module_name = "bonbon_speech.speech_node"
            msg.status = self._HEALTH_OK if overall_ok else self._HEALTH_ERROR
            msg.status_text = (
                self._cfg.summary() if overall_ok else self._error_msg or "pipeline degraded"
            )
            msg.uptime_sec = 0.0  # watchdog does not require uptime
            msg.latency_ms = 0.0
            msg.error_count = 0
            self._pub_health.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"health publish error: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SpeechNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
