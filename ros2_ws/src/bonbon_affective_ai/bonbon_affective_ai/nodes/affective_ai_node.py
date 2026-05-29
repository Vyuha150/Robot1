"""ROS2 LifecycleNode that orchestrates all affective AI processing."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import rclpy
    from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn
    from rclpy.lifecycle.node import LifecycleState
    from rclpy.qos import (
        QoSDurabilityPolicy,
        QoSProfile,
        QoSReliabilityPolicy,
        QoSHistoryPolicy,
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
        self._latest_face_msgs: Dict[str, Any] = {}   # person_id -> FaceEmotion
        self._latest_voice_msgs: Dict[str, Any] = {}  # person_id -> VoiceEmotion
        self._latest_text_msg: Optional[Any] = None
        self._latest_gesture_states: Dict[str, str] = defaultdict(lambda: "none")
        self._tracked_persons: List[Any] = []  # PersonState list

        # Audio accumulation buffer.
        self._audio_buffer: List[float] = []
        self._audio_sample_rate: int = 16000

        # Thread pool for backend inference.
        self._executor: Optional[ThreadPoolExecutor] = None
        self._pending_face_futures: Dict[int, Future] = {}

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
            self.get_logger().error("on_configure failed: %s", exc)
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
            self.get_logger().error("on_activate failed: %s", exc)
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
            "AffectiveAINode: error in state %s.  Transitioning to UNCONFIGURED.",
            state.label,
        )
        return TransitionCallbackReturn.SUCCESS

    # ── Configuration helpers ─────────────────────────────────────────────────

    def _do_configure(self) -> None:
        """Internal: create all sub-systems and I/O handles."""
        from ..config.affective_config import AffectiveConfig
        from ..privacy.privacy_gate import PrivacyGate
        from ..health.health_monitor import AffectiveAIHealthMonitor
        from ..fusion.emotion_fusion_engine import EmotionFusionEngine
        from ..analyzers.text_emotion_analyzer import TextEmotionAnalyzer
        from ..analyzers.face_emotion_analyzer import FaceEmotionAnalyzer
        from ..analyzers.voice_emotion_analyzer import VoiceEmotionAnalyzer

        # ── Parameters & config ───────────────────────────────────────────────
        self._config = AffectiveConfig.from_node(self)
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
        self._text_analyzer = TextEmotionAnalyzer(
            self._config, self._privacy_gate, clock
        )

        # ── Publishers ────────────────────────────────────────────────────────
        from bonbon_msgs.msg import (  # type: ignore[import]
            FaceEmotion, VoiceEmotion, TextEmotion, HumanEmotionState
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
        from bonbon_msgs.msg import PersonStateArray, AudioChunk, GestureEvent  # type: ignore[import]
        from bonbon_msgs.msg import SafetyState  # type: ignore[import]
        from bonbon_msgs.msg import SpeechCommand  # type: ignore[import]

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
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="affective_ai"
        )

        self.get_logger().info("AffectiveAINode configured successfully.")

    def _do_activate(self) -> None:
        """Internal: warm up backends and start processing timers."""
        self._processing_enabled = True

        # Warm up backends asynchronously so the activate call returns quickly.
        if self._executor is not None:
            self._executor.submit(self._warmup_backends)

        # Fusion timer.
        fusion_period_ns: int = int(1e9 / max(self._config.fusion_update_hz, 0.1))
        self._fusion_timer = self.create_timer(
            1.0 / max(self._config.fusion_update_hz, 0.1),
            self._run_fusion,
        )

        # Status publish timer (every 5 s).
        self._status_timer = self.create_timer(5.0, self._publish_status)

        self.get_logger().info(
            "AffectiveAINode activated.  Fusion at %.1f Hz.",
            self._config.fusion_update_hz,
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
                self.get_logger().warn("Face backend warmup error: %s", exc)

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
                self.get_logger().warn("Voice backend warmup error: %s", exc)

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
                self._executor.submit(self._run_voice_analysis, audio_snapshot, sr)

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
            self._executor.submit(
                self._run_text_analysis, msg.text, person_id, 0
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
                    "Safety state %s — disabling affective AI processing.",
                    msg.state_name,
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
                self._latest_voice_msgs["_global"] = result
                if not result.model_failed:
                    self._health_monitor.record_voice_success()
                    self._pub_voice_emotion.publish(result)
        except Exception as exc:
            self._health_monitor.record_voice_failure(str(exc))
            self.get_logger().debug("Voice analysis error: %s", exc)

    def _run_text_analysis(
        self, text: str, person_id: str, tracking_id: int
    ) -> None:
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
            self.get_logger().debug("Text analysis error: %s", exc)

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
            result = self._face_analyzer.analyze_face_crop(
                face_img, tracking_id, person_id
            )
            if result is not None:
                self._latest_face_msgs[person_id] = result
                if not result.low_quality_input:
                    self._health_monitor.record_face_success()
                self._pub_face_emotion.publish(result)
        except Exception as exc:
            self._health_monitor.record_face_failure(str(exc))
            self.get_logger().debug("Face analysis error: %s", exc)

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
                self.get_logger().debug("Fusion error for %s: %s", person_id, exc)

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
                "Privacy mode set to enabled=%s level='%s' by operator '%s'.",
                request.enabled,
                request.level,
                request.operator_id,
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
            self.get_logger().debug("Status publish error: %s", exc)

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
            self.get_logger().debug("Diagnostic publish error: %s", exc)

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
            logger.warning(
                "Unknown face backend '%s', falling back to mock.", name
            )
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
            logger.warning(
                "Unknown voice backend '%s', falling back to mock.", name
            )
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
