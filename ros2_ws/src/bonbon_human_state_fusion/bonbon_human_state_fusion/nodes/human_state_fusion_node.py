"""HumanStateFusionNode — per-person multi-modal state fusion LifecycleNode.

Consumes (does not re-derive any of them):
    /bonbon/persons/tracks            (bonbon_msgs/PersonTrack)        — authoritative identity
    /bonbon/affective/human_state     (bonbon_msgs/HumanEmotionState)  — bridged via raw_track_id
    /bonbon/affective/face_emotion    (bonbon_msgs/FaceEmotion)        — bridged via raw_track_id
    /bonbon/affective/voice_emotion   (bonbon_msgs/VoiceEmotion)       — bridged via raw_track_id
    /bonbon/gesture/events            (bonbon_msgs/GestureEvent)       — direct (person_track_id)
    /bonbon/speaker/turns             (bonbon_msgs/SpeakerTurn)        — direct (person_track_id)
    /perception/intent                (bonbon_msgs/UserIntent)         — bridged via active speaker
    /bonbon/affective/text_emotion    (bonbon_msgs/TextEmotion)        — bridged via active speaker
    /bonbon/safety/state              (bonbon_msgs/SafetyState)

Publishes:
    /bonbon/human/state                                    (bonbon_msgs/HumanState)
    /bonbon/human/human_state_fusion_node/health            (bonbon_msgs/ModuleHealth)

Services:
    ~/health_check  (bonbon_srvs/HealthCheck)
"""

from __future__ import annotations

import time
import uuid

import rclpy
from bonbon_msgs.msg import (
    FaceEmotion,
    GestureEvent,
    HumanEmotionState,
    HumanState,
    ModuleHealth,
    PersonTrack,
    SafetyState,
    SpeakerTurn,
    TextEmotion,
    UserIntent,
    VoiceEmotion,
)
from bonbon_srvs.srv import HealthCheck
from geometry_msgs.msg import Point
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header

from bonbon_human_state_fusion.core.focus_publish_gate import FocusPublishGate
from bonbon_human_state_fusion.core.human_state_fusion_engine import HumanStateFusionEngine

_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_SOURCE_MODULE = "bonbon_human_state_fusion"

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


def _now_header(node: LifecycleNode, frame_id: str = "map") -> Header:
    h = Header()
    h.stamp = node.get_clock().now().to_msg()
    h.frame_id = frame_id
    return h


class HumanStateFusionNode(LifecycleNode):
    def __init__(self, node_name: str = "human_state_fusion_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("publish_rate_hz", 10.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("speaking_window_sec", 2.0)
        self.declare_parameter("recently_spoke_window_sec", 15.0)
        self.declare_parameter("privacy_mode", False)
        self.declare_parameter("background_publish_every_n_cycles", 3)

        self._engine: HumanStateFusionEngine | None = None
        self._focus_gate: FocusPublishGate | None = None
        self._privacy_mode = False

        self._sub_person_tracks = None
        self._sub_human_emotion = None
        self._sub_face_emotion = None
        self._sub_voice_emotion = None
        self._sub_gesture = None
        self._sub_speaker_turn = None
        self._sub_user_intent = None
        self._sub_text_emotion = None
        self._sub_safety = None
        self._pub_state: LifecyclePublisher | None = None
        self._pub_health: LifecyclePublisher | None = None
        self._srv_health = None
        self._timer = None
        self._health_timer = None

        self._node_start = time.monotonic()
        self._cycle_count = 0
        self._error_count = 0
        self._last_cycle_t = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("HumanStateFusionNode: configuring …")
        try:
            gp = self.get_parameter
            self._engine = HumanStateFusionEngine(
                speaking_window_sec=float(
                    gp("speaking_window_sec").get_parameter_value().double_value
                ),
                recently_spoke_window_sec=float(
                    gp("recently_spoke_window_sec").get_parameter_value().double_value
                ),
            )
            self._focus_gate = FocusPublishGate(
                background_publish_every_n_cycles=int(
                    gp("background_publish_every_n_cycles").get_parameter_value().integer_value
                )
            )
            self._privacy_mode = bool(gp("privacy_mode").get_parameter_value().bool_value)
            self.get_logger().info("HumanStateFusionNode: configured")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("HumanStateFusionNode: activating …")
        try:
            rate_hz = self.get_parameter("publish_rate_hz").get_parameter_value().double_value
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value

            self._sub_person_tracks = self.create_subscription(
                PersonTrack,
                "/bonbon/persons/tracks",
                self._cb_person_track,
                _QOS_RELIABLE,
            )
            self._sub_human_emotion = self.create_subscription(
                HumanEmotionState,
                "/bonbon/affective/human_state",
                self._cb_human_emotion,
                _QOS_RELIABLE,
            )
            self._sub_face_emotion = self.create_subscription(
                FaceEmotion,
                "/bonbon/affective/face_emotion",
                self._cb_face_emotion,
                _QOS_RELIABLE,
            )
            self._sub_voice_emotion = self.create_subscription(
                VoiceEmotion,
                "/bonbon/affective/voice_emotion",
                self._cb_voice_emotion,
                _QOS_RELIABLE,
            )
            self._sub_gesture = self.create_subscription(
                GestureEvent,
                "/bonbon/gesture/events",
                self._cb_gesture,
                _QOS_RELIABLE,
            )
            self._sub_speaker_turn = self.create_subscription(
                SpeakerTurn,
                "/bonbon/speaker/turns",
                self._cb_speaker_turn,
                _QOS_RELIABLE,
            )
            self._sub_user_intent = self.create_subscription(
                UserIntent,
                "/perception/intent",
                self._cb_user_intent,
                _QOS_RELIABLE,
            )
            self._sub_text_emotion = self.create_subscription(
                TextEmotion,
                "/bonbon/affective/text_emotion",
                self._cb_text_emotion,
                _QOS_RELIABLE,
            )
            self._sub_safety = self.create_subscription(
                SafetyState,
                "/bonbon/safety/state",
                self._cb_safety,
                _QOS_TRANSIENT,
            )

            self._pub_state = self.create_lifecycle_publisher(
                HumanState,
                "/bonbon/human/state",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/human/human_state_fusion_node/health",
                _QOS_RELIABLE,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )

            self._timer = self.create_timer(1.0 / max(rate_hz, 0.1), self._cb_publish_timer)
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("HumanStateFusionNode: active")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_activate failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("HumanStateFusionNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("HumanStateFusionNode: cleaning up …")
        self._engine = None
        self._focus_gate = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("HumanStateFusionNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_person_track(self, msg: PersonTrack) -> None:
        if self._engine is None:
            return
        self._engine.update_person_track(
            person_track_id=msg.person_track_id,
            known_person_id=msg.known_person_id,
            lifecycle_state=msg.lifecycle_state,
            raw_track_id=msg.raw_track_id,
            x=msg.position_3d.x,
            y=msg.position_3d.y,
            z=msg.position_3d.z,
            confidence=msg.confidence,
        )

    def _cb_human_emotion(self, msg: HumanEmotionState) -> None:
        if self._engine is None:
            return
        self._engine.update_human_emotion_state(
            raw_person_id=msg.person_id,
            dominant_state=msg.dominant_state,
            dominant_confidence=msg.dominant_confidence,
            recommended_response_style=msg.recommended_response_style,
            recommended_distance_m=msg.recommended_distance_m,
            requires_operator_alert=msg.requires_operator_alert,
        )

    def _cb_face_emotion(self, msg: FaceEmotion) -> None:
        if self._engine is not None:
            self._engine.update_face_emotion(msg.person_id, msg.dominant_emotion)

    def _cb_voice_emotion(self, msg: VoiceEmotion) -> None:
        if self._engine is not None:
            self._engine.update_voice_emotion(msg.person_id, msg.dominant_emotion)

    def _cb_gesture(self, msg: GestureEvent) -> None:
        if self._engine is not None:
            self._engine.update_gesture_event(
                msg.person_track_id,
                msg.gesture_type,
                msg.confidence,
                msg.requires_immediate_response,
            )

    def _cb_speaker_turn(self, msg: SpeakerTurn) -> None:
        if self._engine is not None:
            self._engine.update_speaker_turn(
                msg.person_track_id, msg.transcript, msg.transcript_confidence
            )

    def _cb_user_intent(self, msg: UserIntent) -> None:
        if self._engine is not None:
            self._engine.update_user_intent(msg.intent_class)

    def _cb_text_emotion(self, msg: TextEmotion) -> None:
        if self._engine is not None:
            self._engine.update_text_emotion(msg.dominant_emotion, msg.emergency_detected)

    def _cb_safety(self, msg: SafetyState) -> None:
        pass  # reserved; this node does not gate on safety state

    # ── Publish cycle ────────────────────────────────────────────────────────

    def _cb_publish_timer(self) -> None:
        if self._engine is None:
            return
        try:
            self._run_cycle()
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error(f"Human state fusion cycle failed: {exc}")

    def _run_cycle(self) -> None:
        stamp = self.get_clock().now().to_msg()
        results = list(self._engine.build_all())
        # Active-person focus: the focus person and new arrivals publish
        # every cycle; background people publish at a reduced cadence;
        # LEFT_SCENE departures are never throttled. See FocusPublishGate.
        decision = self._focus_gate.select(results)
        for result in decision.to_publish:
            self._pub_state.publish(self._to_ros(result, stamp))
        self._engine.evict_left_scene()

    def _to_ros(self, r, stamp) -> HumanState:
        msg = HumanState()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.event_id = str(uuid.uuid4())
        msg.estimated_at = stamp
        msg.source_module = _SOURCE_MODULE

        msg.person_track_id = r.person_track_id
        msg.known_person_id = "" if self._privacy_mode else r.known_person_id
        msg.lifecycle_state = r.lifecycle_state

        msg.active_speaker_status = r.active_speaker_status
        msg.last_transcript = r.last_transcript
        msg.transcript_confidence = float(r.transcript_confidence)

        msg.current_gesture = r.current_gesture
        msg.gesture_confidence = float(r.gesture_confidence)

        msg.face_expression = r.face_expression
        msg.voice_emotion = r.voice_emotion
        msg.text_intent = r.text_intent
        msg.text_sentiment = r.text_sentiment
        msg.emotional_state = r.emotional_state

        msg.location_relative_to_robot = Point(x=r.location_x, y=r.location_y, z=r.location_z)
        msg.proximity_zone = r.proximity_zone

        msg.engagement_level = float(r.engagement_level)
        msg.urgency_level = float(r.urgency_level)
        msg.confidence = float(r.confidence)

        msg.recommended_robot_response_style = r.recommended_robot_response_style
        msg.recommended_robot_distance_m = float(r.recommended_robot_distance_m)
        msg.requires_operator_alert = r.requires_operator_alert

        msg.evidence_summary = r.evidence_summary
        return msg

    # ── Health ───────────────────────────────────────────────────────────────

    def _health_status(self) -> tuple:
        now = time.monotonic()
        if self._last_cycle_t and (now - self._last_cycle_t) > 3.0:
            return _HEALTH_STALE, "publish cycle stalled"
        if self._error_count > 0 and self._cycle_count == 0:
            return _HEALTH_ERROR, "all cycles failing"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} cycle error(s)"
        if self._engine is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_human_state_fusion.human_state_fusion_node"
        msg.status = status
        msg.status_text = text
        msg.uptime_sec = float(time.monotonic() - self._node_start)
        msg.last_successful_cycle_sec = float(
            (time.monotonic() - self._last_cycle_t) if self._last_cycle_t else -1.0
        )
        msg.cpu_percent = 0.0
        msg.memory_mb = 0.0
        msg.latency_ms = 0.0
        msg.error_count = int(self._error_count)
        msg.warning_count = 0
        msg.processed_count = int(self._cycle_count)
        self._pub_health.publish(msg)

    def _handle_health_check(self, request, response):
        status, text = self._health_status()
        response.healthy = status in (_HEALTH_OK, _HEALTH_WARN)
        response.status = text
        response.warnings = [text] if status == _HEALTH_WARN else []
        response.errors = [text] if status in (_HEALTH_ERROR, _HEALTH_STALE) else []
        response.uptime_sec = float(time.monotonic() - self._node_start)
        return response

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _destroy_active_resources(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None
        for attr in (
            "_sub_person_tracks",
            "_sub_human_emotion",
            "_sub_face_emotion",
            "_sub_voice_emotion",
            "_sub_gesture",
            "_sub_speaker_turn",
            "_sub_user_intent",
            "_sub_text_emotion",
            "_sub_safety",
            "_pub_state",
            "_pub_health",
            "_srv_health",
        ):
            resource = getattr(self, attr, None)
            if resource is not None:
                for destroy in (
                    self.destroy_publisher,
                    self.destroy_subscription,
                    self.destroy_service,
                ):
                    try:
                        destroy(resource)  # type: ignore[arg-type]
                        break
                    except Exception:  # noqa: BLE001
                        continue
                setattr(self, attr, None)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = HumanStateFusionNode("human_state_fusion_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
