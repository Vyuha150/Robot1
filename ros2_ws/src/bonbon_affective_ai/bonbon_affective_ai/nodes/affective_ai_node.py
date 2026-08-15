"""ROS2 LifecycleNode that orchestrates all affective AI processing."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue

_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_PI_EFFICIENCY_PROFILE_PATH = _REPO_ROOT / "config" / "pi_efficiency_profile.yaml"


@dataclass(frozen=True)
class SpeakerTurnVoiceEmotion:
    """Duck-typed stand-in for a VoiceEmotion message, built from a
    SpeakerTurn's own voice_emotion/emotion_confidence fields.
    EmotionFusionEngine.fuse() only ever reads dominant_emotion/
    dominant_confidence/model_failed off a "voice" object via getattr(),
    so this minimal shape is sufficient -- no real VoiceEmotion message
    is fabricated or re-published from this."""

    dominant_emotion: str
    dominant_confidence: float
    model_failed: bool = False


try:
    import rclpy
    from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
    from rclpy.lifecycle.node import LifecycleState
    from rclpy.qos import (
        QoSDurabilityPolicy,
        QoSHistoryPolicy,
        QoSProfile,
        QoSReliabilityPolicy,
    )
    from std_msgs.msg import String

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False

logger = logging.getLogger(__name__)

_RELIABLE_QOS = None
_TRANSIENT_LOCAL_QOS = None

if _ROS2_AVAILABLE:
    _RELIABLE_QOS = QoSProfile(
        reliability=QoSReliabilityPolicy.RELIABLE,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=10,
    )
    _TRANSIENT_LOCAL_QOS = QoSProfile(
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=1,
    )


class AffectiveAINode(LifecycleNode):
    """Central affective AI lifecycle node.

    Subscribes to person tracks, audio chunks, speech commands, safety state,
    and gesture events.  Publishes face, voice, text emotion messages and fused
    HumanEmotionState.  Exposes services for on-demand text analysis, health
    checks, and privacy control.

    Lifecycle transitions:
    - ``on_configure``: Declare + read parameters; create backends, analyzers,
      publishers, subscribers, and services.
    - ``on_activate``: Warm up backends in a thread pool; start the fusion timer.
    - ``on_deactivate``: Cancel the fusion timer; stop accepting new inputs.
    - ``on_cleanup``: Tear down executor and backend references.
    - ``on_error``: Log and transition to UNCONFIGURED.
    """

    def __init__(self) -> None:
        """Create the node without allocating any heavy resources."""
        super().__init__("affective_ai_node")

        # Sub-system handles — populated in on_configure / on_activate.
        self._config = None
        self._privacy_gate = None
        self._face_backend = None
        self._voice_backend = None
        self._face_analyzer = None
        self._voice_analyzer = None
        self._text_analyzer = None
        self._fusion_engine = None
        self._health_monitor = None

        # ROS2 I/O handles.
        self._pub_face_emotion = None
        self._pub_voice_emotion = None
        self._pub_text_emotion = None
        self._pub_human_state = None
        self._pub_status = None
        self._pub_diagnostics = None

        self._sub_persons = None
        self._sub_audio = None
        self._sub_command = None
        self._sub_safety = None
        self._sub_gesture = None

        self._srv_analyze_text = None
        self._srv_health_check = None
        self._srv_set_privacy = None

        self._fusion_timer = None
        self._status_timer = None

        # State tracking.
        self._processing_enabled: bool = True
        self._latest_face_msgs: Dict[str, Any] = {}  # person_id -> FaceEmotion
        self._latest_voice_msgs: Dict[str, Any] = {}  # person_id -> VoiceEmotion
        self._latest_text_msg: Optional[Any] = None
        self._latest_gesture_states: Dict[str, str] = defaultdict(lambda: "none")
        self._tracked_persons: List[Any] = []  # PersonState list

        # person_track_id (bonbon_multi_person_tracker's stable, cross-frame
        # ID space) -> raw_track_id (bonbon_vision's per-frame PersonState.
        # track_id space, what this node's own person_id keys are in --
        # see bonbon_msgs/PersonTrack.msg's own raw_track_id field comment).
        # Needed because /bonbon/speaker/turns (SpeakerTurn) attributes voice
        # emotion in person_track_id space, but _latest_voice_msgs/
        # _fuse_and_publish key everything in raw_track_id space -- without
        # this bridge, storing SpeakerTurn's voice_emotion would silently
        # never match any lookup here (the same dead-lookup shape this fix
        # targets, just moved one level up). Entries are removed (not kept
        # stale) whenever raw_track_id goes empty (temporarily_lost), since
        # a stale raw id could misattribute a future frame's re-used number.
        self._person_track_to_raw_id: Dict[str, str] = {}

        # Audio accumulation buffer.
        self._audio_buffer: List[float] = []
        self._audio_sample_rate: int = 16000

        # Thread pool for backend inference.
        self._executor: Optional[ThreadPoolExecutor] = None
        self._pending_face_futures: Dict[int, Future] = {}

        # Backpressure gates in front of the thread pool — addresses the
        # audit finding that voice/text analysis were submitted with no
        # admission control, so a slow backend under load would let queued
        # work grow unbounded inside the executor. Drop-newest: a fresh
        # audio/text sample is generally more useful than one that's been
        # waiting, and completing in-flight work beats discarding it.
        self._voice_queue = BoundedInferenceQueue(max_depth=4)
        self._text_queue = BoundedInferenceQueue(max_depth=4)

        self._start_time: float = time.time()

    # ── Lifecycle callbacks ───────────────────────────────────────────────────

    def on_configure(self, state: "LifecycleState") -> "TransitionCallbackReturn":
        """Configure the node: load params, create all sub-systems and I/O.

        Args:
            state: Previous lifecycle state (unused; provided by the framework).

        Returns:
            TransitionCallbackReturn.SUCCESS on success, FAILURE otherwise.
        """
        self.get_logger().info("AffectiveAINode: configuring …")
        try:
            self._do_configure()
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f"on_configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: "LifecycleState") -> "TransitionCallbackReturn":
        """Activate the node: warm up backends and start the fusion timer.

        Args:
            state: Previous lifecycle state.

        Returns:
            TransitionCallbackReturn.SUCCESS on success, FAILURE otherwise.
        """
        self.get_logger().info("AffectiveAINode: activating …")
        try:
            self._do_activate()
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f"on_activate failed: {exc}")
            return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state: "LifecycleState") -> "TransitionCallbackReturn":
        """Deactivate the node: stop timers and prevent new processing.

        Args:
            state: Previous lifecycle state.

        Returns:
            TransitionCallbackReturn.SUCCESS.
        """
        self.get_logger().info("AffectiveAINode: deactivating …")
        self._processing_enabled = False
        if self._fusion_timer is not None:
            self._fusion_timer.cancel()
            self._fusion_timer = None
        if self._status_timer is not None:
            self._status_timer.cancel()
            self._status_timer = None
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: "LifecycleState") -> "TransitionCallbackReturn":
        """Clean up all resources.

        Args:
            state: Previous lifecycle state.

        Returns:
            TransitionCallbackReturn.SUCCESS.
        """
        self.get_logger().info("AffectiveAINode: cleaning up …")
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._face_backend = None
        self._voice_backend = None
        return TransitionCallbackReturn.SUCCESS

    def on_error(self, state: "LifecycleState") -> "TransitionCallbackReturn":
        """Handle lifecycle error — log and attempt to stay recoverable.

        Args:
            state: State at the time of the error.

        Returns:
            TransitionCallbackReturn.SUCCESS (transition to UNCONFIGURED).
        """
        self.get_logger().error(
            f"AffectiveAINode: error in state {state.label}.  Transitioning to UNCONFIGURED."
        )
        return TransitionCallbackReturn.SUCCESS

    # ── Configuration helpers ─────────────────────────────────────────────────

    def _apply_pi_wide_face_fps_cap(self, config: "AffectiveConfig") -> None:  # type: ignore[name-defined] # noqa: F821
        """Raises config.face_sample_interval_sec (never lowers it) so the
        effective face-emotion rate never exceeds
        config/pi_efficiency_profile.yaml's fps_limits.face_emotion --
        Phase 7 remainder, docs/PERCEPTION_AI_CURRENT_AUDIT.md item 30
        (declared in shared config but never read by this module).
        voice_emotion's yaml value is 0 (event-gated by design, not a
        steady rate per the file's own comment) -- no cap applies there.
        """
        try:
            from bonbon_perception_efficiency.core.pi_efficiency_profile import (
                PiEfficiencyProfile,
            )

            profile = PiEfficiencyProfile.load(_DEFAULT_PI_EFFICIENCY_PROFILE_PATH)
            fps = profile.fps_limit("face_emotion")
            if fps and fps > 0.0:
                min_interval = 1.0 / fps
                if min_interval > config.face_sample_interval_sec:
                    self.get_logger().info(
                        f"AffectiveAINode: Pi-wide FPS cap loaded from "
                        f"{_DEFAULT_PI_EFFICIENCY_PROFILE_PATH} -> {fps} FPS "
                        f"(face_sample_interval_sec {config.face_sample_interval_sec:.3f} -> "
                        f"{min_interval:.3f})"
                    )
                    config.face_sample_interval_sec = min_interval
        except Exception as exc:
            self.get_logger().warning(
                f"AffectiveAINode: could not load pi_efficiency_profile ({exc}) -- "
                "Pi-wide FPS cap disabled, face_sample_interval_sec unchanged."
            )

    def _do_configure(self) -> None:
        """Internal: create all sub-systems and I/O handles."""
        from ..analyzers.face_emotion_analyzer import FaceEmotionAnalyzer
        from ..analyzers.text_emotion_analyzer import TextEmotionAnalyzer
        from ..analyzers.voice_emotion_analyzer import VoiceEmotionAnalyzer
        from ..config.affective_config import AffectiveConfig
        from ..fusion.emotion_fusion_engine import EmotionFusionEngine
        from ..health.health_monitor import AffectiveAIHealthMonitor
        from ..privacy.privacy_gate import PrivacyGate

        # ── Parameters & config ───────────────────────────────────────────────
        self._config = AffectiveConfig.from_node(self)
        self._apply_pi_wide_face_fps_cap(self._config)
        self._privacy_gate = PrivacyGate(self._config)
        self._health_monitor = AffectiveAIHealthMonitor()
        self._fusion_engine = EmotionFusionEngine(self._config)

        # ── Backends ──────────────────────────────────────────────────────────
        self._face_backend = self._create_face_backend(self._config.face_backend)
        self._voice_backend = self._create_voice_backend(self._config.voice_backend)

        # ── Analyzers ─────────────────────────────────────────────────────────
        clock = self.get_clock()
        self._face_analyzer = FaceEmotionAnalyzer(
            self._config, self._face_backend, self._privacy_gate, clock
        )
        self._voice_analyzer = VoiceEmotionAnalyzer(
            self._config, self._voice_backend, self._privacy_gate, clock
        )
        self._text_analyzer = TextEmotionAnalyzer(self._config, self._privacy_gate, clock)

        # ── Publishers ────────────────────────────────────────────────────────
        from bonbon_msgs.msg import (  # type: ignore[import]
            FaceEmotion,
            HumanEmotionState,
            TextEmotion,
            VoiceEmotion,
        )

        self._pub_face_emotion = self.create_publisher(
            FaceEmotion, "/bonbon/affective/face_emotion", _RELIABLE_QOS
        )
        self._pub_voice_emotion = self.create_publisher(
            VoiceEmotion, "/bonbon/affective/voice_emotion", _RELIABLE_QOS
        )
        self._pub_text_emotion = self.create_publisher(
            TextEmotion, "/bonbon/affective/text_emotion", _RELIABLE_QOS
        )
        self._pub_human_state = self.create_publisher(
            HumanEmotionState, "/bonbon/affective/human_state", _RELIABLE_QOS
        )
        self._pub_status = self.create_publisher(
            String, "/bonbon/affective/status", _TRANSIENT_LOCAL_QOS
        )
        self._pub_diagnostics = self.create_publisher(
            String, "/bonbon/diagnostics/events", _RELIABLE_QOS
        )

        # ── Subscribers ───────────────────────────────────────────────────────
        from bonbon_msgs.msg import (  # type: ignore[import]
            AudioChunk,
            GestureEvent,
            PersonStateArray,
            PersonTrack,  # type: ignore[import]
            SafetyState,  # type: ignore[import]
            SpeakerTurn,  # type: ignore[import]
            SpeechCommand,  # type: ignore[import]
        )

        self._sub_persons = self.create_subscription(
            PersonStateArray,
            "/bonbon/vision/persons",
            self._cb_persons,
            _RELIABLE_QOS,
        )
        self._sub_audio = self.create_subscription(
            AudioChunk,
            "/bonbon/speech/audio",
            self._cb_audio,
            _RELIABLE_QOS,
        )
        self._sub_command = self.create_subscription(
            SpeechCommand,
            "/speech/command",
            self._cb_transcript,
            _RELIABLE_QOS,
        )
        self._sub_safety = self.create_subscription(
            SafetyState,
            "/bonbon/safety/state",
            self._cb_safety,
            _TRANSIENT_LOCAL_QOS,
        )
        self._sub_gesture = self.create_subscription(
            GestureEvent,
            "/bonbon/gesture/events",
            self._cb_gesture,
            _RELIABLE_QOS,
        )
        self._sub_person_track = self.create_subscription(
            PersonTrack,
            "/bonbon/persons/tracks",
            self._cb_person_track,
            _RELIABLE_QOS,
        )
        self._sub_speaker_turn = self.create_subscription(
            SpeakerTurn,
            "/bonbon/speaker/turns",
            self._cb_speaker_turn,
            _RELIABLE_QOS,
        )

        # ── Services ──────────────────────────────────────────────────────────
        from bonbon_srvs.srv import AnalyzeText, HealthCheck, SetPrivacyMode  # type: ignore[import]

        self._srv_analyze_text = self.create_service(
            AnalyzeText,
            "/bonbon/affective/analyze_text",
            self._handle_analyze_text,
        )
        self._srv_health_check = self.create_service(
            HealthCheck,
            "/bonbon/affective/health_check",
            self._handle_health_check,
        )
        self._srv_set_privacy = self.create_service(
            SetPrivacyMode,
            "/bonbon/affective/set_privacy_mode",
            self._handle_set_privacy,
        )

        # ── Thread pool ───────────────────────────────────────────────────────
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="affective_ai")

        self.get_logger().info("AffectiveAINode configured successfully.")

    def _do_activate(self) -> None:
        """Internal: warm up backends and start processing timers."""
        self._processing_enabled = True

        # Warm up backends asynchronously so the activate call returns quickly.
        if self._executor is not None:
            self._executor.submit(self._warmup_backends)

        # Fusion timer.
        self._fusion_timer = self.create_timer(
            1.0 / max(self._config.fusion_update_hz, 0.1),
            self._run_fusion,
        )

        # Status publish timer (every 5 s).
        self._status_timer = self.create_timer(5.0, self._publish_status)

        self.get_logger().info(
            f"AffectiveAINode activated.  Fusion at {self._config.fusion_update_hz:.1f} Hz."
        )

    def _warmup_backends(self) -> None:
        """Run backend warmup in the thread pool.  Called on activation."""
        if self._face_backend is not None and self._config.face_enabled:
            try:
                self._face_backend.warmup()
                if self._face_backend.is_ready:
                    self._health_monitor.record_face_success()
                    self.get_logger().info("Face backend ready.")
                else:
                    self._health_monitor.record_face_failure("not_ready_after_warmup")
                    self.get_logger().warn("Face backend not ready after warmup.")
            except Exception as exc:
                self._health_monitor.record_face_failure(str(exc))
                self.get_logger().warn(f"Face backend warmup error: {exc}")

        if self._voice_backend is not None and self._config.voice_enabled:
            try:
                self._voice_backend.warmup()
                if self._voice_backend.is_ready:
                    self._health_monitor.record_voice_success()
                    self.get_logger().info("Voice backend ready.")
                else:
                    self._health_monitor.record_voice_failure("not_ready_after_warmup")
                    self.get_logger().warn("Voice backend not ready after warmup.")
            except Exception as exc:
                self._health_monitor.record_voice_failure(str(exc))
                self.get_logger().warn(f"Voice backend warmup error: {exc}")

    # ── Subscriber callbacks ──────────────────────────────────────────────────

    def _cb_persons(self, msg: Any) -> None:
        """Handle PersonStateArray messages from bonbon_vision.

        Stores the current person list for the fusion loop.  For each person,
        face analysis is marked pending; actual face crops require a camera
        frame that is not available directly from PersonStateArray.

        Args:
            msg: ``PersonStateArray`` message.
        """
        if not self._processing_enabled:
            return
        self._tracked_persons = list(msg.persons)

    def _cb_audio(self, msg: Any) -> None:
        """Buffer incoming AudioChunk samples and trigger voice analysis.

        Accumulates PCM data in ``_audio_buffer``.  When the buffer represents
        at least ``voice_segment_min_sec`` of audio, the buffer is flushed and
        submitted for voice analysis in the thread pool.

        Args:
            msg: ``AudioChunk`` message.
        """
        if not self._processing_enabled:
            return
        if not self._config.voice_enabled:
            return

        self._audio_sample_rate = int(msg.sample_rate)
        self._audio_buffer.extend(msg.data)

        # Determine current buffered duration.
        buffered_sec: float = len(self._audio_buffer) / max(self._audio_sample_rate, 1)
        if buffered_sec >= self._config.voice_segment_min_sec:
            audio_snapshot = np.array(self._audio_buffer, dtype=np.float32)
            self._audio_buffer = []
            sr = self._audio_sample_rate

            if self._executor is not None:
                admit = self._voice_queue.try_admit()
                if admit.admitted:
                    self._executor.submit(self._run_voice_analysis, audio_snapshot, sr)
                else:
                    self.get_logger().debug(
                        f"Voice analysis queue full (depth={admit.queue_depth}) — dropping segment."
                    )

    def _cb_transcript(self, msg: Any) -> None:
        """Handle SpeechCommand messages and run text analysis.

        Args:
            msg: ``SpeechCommand`` message.  The ``text`` field is analysed.
        """
        if not self._processing_enabled:
            return
        if not self._config.text_enabled:
            return
        if not msg.text:
            return

        person_id: str = getattr(msg, "speaker_id", "") or ""
        if self._executor is not None:
            admit = self._text_queue.try_admit()
            if admit.admitted:
                self._executor.submit(self._run_text_analysis, msg.text, person_id, 0)
            else:
                self.get_logger().debug(
                    f"Text analysis queue full (depth={admit.queue_depth}) — dropping transcript."
                )

    def _cb_safety(self, msg: Any) -> None:
        """Handle SafetyState messages and disable processing on FAULT/SAFE_STOP.

        Args:
            msg: ``SafetyState`` message.
        """
        # SafetyState constants: SAFE_STOP=7, FAULT=6
        if msg.state in (6, 7):
            if self._processing_enabled:
                self.get_logger().warn(
                    f"Safety state {msg.state_name} — disabling affective AI processing."
                )
            self._processing_enabled = False
        else:
            self._processing_enabled = True

    def _cb_gesture(self, msg: Any) -> None:
        """Handle GestureEvent messages from bonbon_gesture.

        Stores the latest gesture type per person for use by the fusion loop.

        Args:
            msg: ``GestureEvent`` message.
        """
        if not self._processing_enabled:
            return
        person_id: str = str(msg.person_id) if msg.person_id else str(msg.tracking_id)
        self._latest_gesture_states[person_id] = str(msg.gesture_type)

        # Emergency gesture — publish alert diagnostic immediately.
        if msg.requires_immediate_response:
            self._publish_diagnostic(
                "gesture_emergency",
                {"person_id": person_id, "gesture": msg.gesture_type},
            )

    def _cb_person_track(self, msg: Any) -> None:
        """Maintain the person_track_id -> raw_track_id bridge from PersonTrack.

        Args:
            msg: ``PersonTrack`` message from bonbon_multi_person_tracker.
        """
        person_track_id = str(getattr(msg, "person_track_id", "") or "")
        raw_track_id = str(getattr(msg, "raw_track_id", "") or "")
        if not person_track_id:
            return
        if raw_track_id:
            self._person_track_to_raw_id[person_track_id] = raw_track_id
        else:
            # temporarily_lost (or otherwise no current raw detection) --
            # drop rather than keep a stale mapping that could misattribute
            # a future frame's re-used raw_track_id number.
            self._person_track_to_raw_id.pop(person_track_id, None)

    def _cb_speaker_turn(self, msg: Any) -> None:
        """Attribute a completed speaker turn's voice emotion to a person.

        SpeakerTurn.voice_emotion is bonbon_speaker_intelligence's own
        best-effort mirror of the most recent (still globally-buffered)
        VoiceEmotion reading, linked to person_track_id via DOA-to-bearing
        association -- see bonbon_speaker_intelligence's
        core/voice_emotion_cache.py for the honest limitation this
        inherits (not a verified per-utterance emotion, the closest
        available attribution). Bridged here to raw_track_id via
        _person_track_to_raw_id so it lands in the same key space
        _fuse_and_publish already looks up -- previously nothing ever
        populated that per-person key, so voice emotion silently fell back
        to (or never reached) the unscoped "_global" entry for every
        person alike.

        Args:
            msg: ``SpeakerTurn`` message from bonbon_speaker_intelligence.
        """
        if not self._processing_enabled:
            return
        person_track_id = str(getattr(msg, "person_track_id", "") or "")
        voice_emotion = str(getattr(msg, "voice_emotion", "") or "")
        if not person_track_id or not voice_emotion:
            return

        raw_track_id = self._person_track_to_raw_id.get(person_track_id)
        if not raw_track_id:
            self.get_logger().debug(
                f"Speaker turn for person_track_id={person_track_id} has no current "
                "raw_track_id mapping yet -- cannot attribute voice emotion to a "
                "specific person this cycle."
            )
            return

        self._latest_voice_msgs[raw_track_id] = SpeakerTurnVoiceEmotion(
            dominant_emotion=voice_emotion,
            dominant_confidence=float(getattr(msg, "emotion_confidence", 0.0) or 0.0),
        )

    # ── Analysis runners (called from thread pool) ────────────────────────────

    def _run_voice_analysis(self, audio: np.ndarray, sample_rate: int) -> None:
        """Run voice analysis in a worker thread and publish the result.

        Args:
            audio: PCM float32 array.
            sample_rate: Sample rate in Hz.
        """
        try:
            result = self._voice_analyzer.analyze_segment(
                audio, sample_rate, tracking_id=0, person_id=""
            )
            if result is not None:
                # AudioChunk carries no speaker attribution at this stage --
                # this raw analyzer result genuinely cannot be scoped to a
                # person here (that only becomes possible downstream, once
                # bonbon_speaker_intelligence links it to a person_track_id
                # via DOA-to-bearing association -- see _cb_speaker_turn,
                # which stores the ATTRIBUTED reading under the real
                # raw_track_id key). "_global" is kept only as the
                # unattributed last-resort _fuse_and_publish falls back to
                # when no per-person entry exists yet.
                self._latest_voice_msgs["_global"] = result
                if not result.model_failed:
                    self._health_monitor.record_voice_success()
                    self._pub_voice_emotion.publish(result)
        except Exception as exc:
            self._health_monitor.record_voice_failure(str(exc))
            self.get_logger().debug(f"Voice analysis error: {exc}")
        finally:
            self._voice_queue.mark_complete()

    def _run_text_analysis(self, text: str, person_id: str, tracking_id: int) -> None:
        """Run text analysis in a worker thread and publish the result.

        Args:
            text: Input text string.
            person_id: Person identifier.
            tracking_id: Integer tracking ID.
        """
        try:
            result = self._text_analyzer.analyze_text(text, person_id, tracking_id)
            if result is not None:
                self._latest_text_msg = result
                self._health_monitor.record_text_success()
                self._pub_text_emotion.publish(result)
                if result.requires_operator_alert:
                    self._publish_diagnostic(
                        "operator_alert",
                        {
                            "reason": result.dominant_emotion,
                            "person_id": person_id,
                            "text_snippet": result.text_snippet,
                        },
                    )
        except Exception as exc:
            self._health_monitor.record_text_failure(str(exc))
            self.get_logger().debug(f"Text analysis error: {exc}")
        finally:
            self._text_queue.mark_complete()

    def _run_face_analysis_for_person(
        self,
        face_img: np.ndarray,
        tracking_id: int,
        person_id: str,
    ) -> None:
        """Run face analysis for a specific person in a worker thread.

        Args:
            face_img: BGR face crop numpy array.
            tracking_id: Integer tracking ID.
            person_id: String person identifier.
        """
        try:
            result = self._face_analyzer.analyze_face_crop(face_img, tracking_id, person_id)
            if result is not None:
                self._latest_face_msgs[person_id] = result
                if not result.low_quality_input:
                    self._health_monitor.record_face_success()
                self._pub_face_emotion.publish(result)
        except Exception as exc:
            self._health_monitor.record_face_failure(str(exc))
            self.get_logger().debug(f"Face analysis error: {exc}")

    # ── Fusion timer callback ─────────────────────────────────────────────────

    def _run_fusion(self) -> None:
        """Fusion timer callback: fuse modalities for each tracked person.

        Called at ``config.fusion_update_hz``.  Must return quickly; heavy
        work is already done in the thread pool.
        """
        if not self._processing_enabled:
            return
        if not self._tracked_persons and not self._latest_face_msgs:
            return

        # Build a person list from tracked persons + any cached face results.
        person_ids: set[str] = {str(p.track_id) for p in self._tracked_persons}
        person_ids.update(self._latest_face_msgs.keys())
        person_ids.discard("")

        for person_id in person_ids:
            try:
                self._fuse_and_publish(person_id)
            except Exception as exc:
                self.get_logger().debug(f"Fusion error for {person_id}: {exc}")

    def _fuse_and_publish(self, person_id: str) -> None:
        """Fuse all available modalities for one person and publish.

        Args:
            person_id: String person identifier.
        """
        face_msg = self._latest_face_msgs.get(person_id)
        voice_msg = self._latest_voice_msgs.get(person_id) or self._latest_voice_msgs.get("_global")
        text_msg = self._latest_text_msg
        gesture = self._latest_gesture_states.get(person_id, "none")

        tracking_id: int = 0
        if face_msg is not None:
            tracking_id = int(face_msg.tracking_id)
        else:
            for p in self._tracked_persons:
                if str(p.track_id) == person_id:
                    # Parse numeric part from e.g. "person_3"
                    try:
                        tracking_id = int(p.track_id.split("_")[-1])
                    except (ValueError, IndexError):
                        tracking_id = hash(person_id) % 100000
                    break

        state_msg = self._fusion_engine.fuse(
            face_msg, voice_msg, text_msg, gesture, person_id, tracking_id
        )
        state_msg.header.stamp = self.get_clock().now().to_msg()
        self._pub_human_state.publish(state_msg)

        if state_msg.requires_operator_alert:
            self._publish_diagnostic(
                "human_state_alert",
                {
                    "person_id": person_id,
                    "state": state_msg.dominant_state,
                    "confidence": state_msg.dominant_confidence,
                },
            )

    # ── Service handlers ──────────────────────────────────────────────────────

    def _handle_analyze_text(self, request: Any, response: Any) -> Any:
        """Handle AnalyzeText service requests synchronously.

        Args:
            request: ``AnalyzeText.Request`` with ``text``, ``person_id``,
                ``context`` fields.
            response: ``AnalyzeText.Response`` to populate.

        Returns:
            The populated response.
        """
        try:
            result = self._text_analyzer.analyze_text(
                request.text,
                person_id=request.person_id,
                tracking_id=0,
                context=request.context,
            )
            response.success = True
            response.result = result
            response.error_message = ""
        except Exception as exc:
            response.success = False
            response.error_message = str(exc)
        return response

    def _handle_health_check(self, request: Any, response: Any) -> Any:
        """Handle HealthCheck service requests.

        Args:
            request: ``HealthCheck.Request`` with ``module_name`` field.
            response: ``HealthCheck.Response`` to populate.

        Returns:
            The populated response.
        """
        status = self._health_monitor.get_status()
        response.healthy = self._health_monitor.is_healthy()
        response.uptime_sec = float(self._health_monitor.uptime_sec)

        warnings: List[str] = []
        errors: List[str] = []

        if not status["face_backend_ok"]:
            warnings.append("Face backend not available")
        if not status["voice_backend_ok"]:
            warnings.append("Voice backend not available")
        if not status["text_backend_ok"]:
            errors.append("Text backend failed")
        if not self._processing_enabled:
            warnings.append("Processing disabled (safety state)")

        for err in status["recent_errors"]:
            errors.append(err)

        response.warnings = warnings
        response.errors = errors
        response.status = "ok" if response.healthy else "degraded"
        return response

    def _handle_set_privacy(self, request: Any, response: Any) -> Any:
        """Handle SetPrivacyMode service requests.

        Args:
            request: ``SetPrivacyMode.Request`` with ``enabled``, ``level``,
                ``operator_id`` fields.
            response: ``SetPrivacyMode.Response`` to populate.

        Returns:
            The populated response.
        """
        previous_level = self._privacy_gate.current_level
        try:
            self._privacy_gate.set_mode(request.enabled, request.level)
            # Also update the config object for consistency.
            self._config.privacy_mode = request.enabled
            self._config.privacy_level = request.level
            response.success = True
            response.previous_level = previous_level
            response.error_message = ""
            self.get_logger().info(
                f"Privacy mode set to enabled={request.enabled} level='{request.level}' "
                f"by operator '{request.operator_id}'."
            )
            self._publish_diagnostic(
                "privacy_mode_changed",
                {
                    "previous": previous_level,
                    "new": request.level,
                    "operator": request.operator_id,
                },
            )
        except ValueError as exc:
            response.success = False
            response.previous_level = previous_level
            response.error_message = str(exc)
        return response

    # ── Status helpers ────────────────────────────────────────────────────────

    def _publish_status(self) -> None:
        """Publish a JSON health status string on the status topic."""
        try:
            status = self._health_monitor.get_status()
            status["node"] = "affective_ai_node"
            status["processing_enabled"] = self._processing_enabled
            status["privacy_level"] = self._privacy_gate.current_level
            status["tracked_persons"] = len(self._tracked_persons)
            payload = String()
            payload.data = json.dumps(status)
            self._pub_status.publish(payload)
        except Exception as exc:
            self.get_logger().debug(f"Status publish error: {exc}")

    def _publish_diagnostic(self, event_type: str, data: dict) -> None:
        """Publish a JSON diagnostic event.

        Args:
            event_type: Short event category string.
            data: Dictionary of additional event fields.
        """
        try:
            payload = String()
            payload.data = json.dumps(
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": event_type,
                    "node": "affective_ai_node",
                    "timestamp": time.time(),
                    **data,
                }
            )
            self._pub_diagnostics.publish(payload)
        except Exception as exc:
            self.get_logger().debug(f"Diagnostic publish error: {exc}")

    # ── Backend factory helpers ───────────────────────────────────────────────

    @staticmethod
    def _create_face_backend(name: str) -> Any:
        """Instantiate the configured face backend.

        Args:
            name: Backend name: 'deepface' or 'mock'.

        Returns:
            FaceBackendInterface implementation (not yet warmed up).
        """
        if name == "deepface":
            from ..backends.deepface_backend import DeepFaceBackend

            return DeepFaceBackend()
        elif name == "mock":
            from ..backends.mock_backends import MockFaceBackend

            return MockFaceBackend()
        else:
            logger.warning("Unknown face backend '%s', falling back to mock.", name)
            from ..backends.mock_backends import MockFaceBackend

            return MockFaceBackend()

    @staticmethod
    def _create_voice_backend(name: str) -> Any:
        """Instantiate the configured voice backend.

        Args:
            name: Backend name: 'speechbrain' or 'mock'.

        Returns:
            VoiceBackendInterface implementation (not yet warmed up).
        """
        if name == "speechbrain":
            from ..backends.speechbrain_backend import SpeechBrainBackend

            return SpeechBrainBackend()
        elif name == "mock":
            from ..backends.mock_backends import MockVoiceBackend

            return MockVoiceBackend()
        else:
            logger.warning("Unknown voice backend '%s', falling back to mock.", name)
            from ..backends.mock_backends import MockVoiceBackend

            return MockVoiceBackend()


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args: Optional[list] = None) -> None:
    """ROS2 node entry point.

    Args:
        args: Optional command-line argument list passed to ``rclpy.init``.
    """
    rclpy.init(args=args)
    node = AffectiveAINode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
