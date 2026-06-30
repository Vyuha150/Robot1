"""SpeakerIntelligenceNode — persistent speaker identity + transcript-to-speaker
mapping + audio-visual person association.

Consumes (does not re-run VAD/STT/diarization, does not re-derive emotion):
    /speech/transcription            (bonbon_msgs/SpeechTranscription) @ per-utterance
    /bonbon/affective/voice_emotion  (bonbon_msgs/VoiceEmotion)
    /bonbon/persons/tracks            (bonbon_msgs/PersonTrack)
    /bonbon/safety/state              (bonbon_msgs/SafetyState)

Publishes:
    /bonbon/speaker/turns                                  (bonbon_msgs/SpeakerTurn)
    /bonbon/speaker/speaker_intelligence_node/health        (bonbon_msgs/ModuleHealth)

Services:
    ~/health_check  (bonbon_srvs/HealthCheck)
"""

from __future__ import annotations

import time

import rclpy
from bonbon_msgs.msg import (
    ModuleHealth,
    PersonTrack,
    SafetyState,
    SpeakerTurn,
    SpeechTranscription,
    VoiceEmotion,
)
from bonbon_srvs.srv import HealthCheck
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header

from bonbon_speaker_intelligence.core.audio_visual_associator import TrackedPersonBearing
from bonbon_speaker_intelligence.core.speaker_identity_manager import (
    SpeakerIdentityConfig,
    SpeakerIdentityManager,
)
from bonbon_speaker_intelligence.core.speaker_turn_builder import SpeakerTurnBuilder
from bonbon_speaker_intelligence.core.transcript_segment_mapper import (
    DiarizationSegment,
    WordTiming,
)
from bonbon_speaker_intelligence.core.voice_emotion_cache import VoiceEmotionCache

_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_SOURCE_MODULE = "bonbon_speaker_intelligence"

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


def _bearing_deg_from_xy(x: float, y: float) -> float:
    import math

    return math.degrees(math.atan2(y, x))


def _offset_stamp(stamp, offset_sec: float):
    """Returns a builtin_interfaces/Time = *stamp* + *offset_sec*."""
    from builtin_interfaces.msg import Time as BuiltinTime

    total_nanosec = stamp.sec * 1_000_000_000 + stamp.nanosec + int(offset_sec * 1_000_000_000)
    out = BuiltinTime()
    out.sec = total_nanosec // 1_000_000_000
    out.nanosec = total_nanosec % 1_000_000_000
    return out


class SpeakerIntelligenceNode(LifecycleNode):
    def __init__(self, node_name: str = "speaker_intelligence_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("doa_tolerance_deg", 20.0)
        self.declare_parameter("recency_window_sec", 8.0)
        self.declare_parameter("voice_emotion_max_age_sec", 3.0)
        self.declare_parameter("short_segment_threshold_sec", 0.3)
        self.declare_parameter("max_bearing_delta_deg", 25.0)
        self.declare_parameter("privacy_mode", False)

        self._builder: SpeakerTurnBuilder | None = None
        self._voice_cache: VoiceEmotionCache | None = None
        self._privacy_mode = False

        self._sub_transcription = None
        self._sub_voice_emotion = None
        self._sub_person_tracks = None
        self._sub_safety = None
        self._pub_turns: LifecyclePublisher | None = None
        self._pub_health: LifecyclePublisher | None = None
        self._srv_health = None
        self._health_timer = None

        self._person_bearings: list[TrackedPersonBearing] = []

        self._node_start = time.monotonic()
        self._cycle_count = 0
        self._error_count = 0
        self._last_cycle_t = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("SpeakerIntelligenceNode: configuring …")
        try:
            gp = lambda name: self.get_parameter(name).get_parameter_value()  # noqa: E731
            identity_cfg = SpeakerIdentityConfig(
                doa_tolerance_deg=float(gp("doa_tolerance_deg").double_value),
                recency_window_sec=float(gp("recency_window_sec").double_value),
            )
            self._voice_cache = VoiceEmotionCache(
                max_age_sec=float(gp("voice_emotion_max_age_sec").double_value)
            )
            self._builder = SpeakerTurnBuilder(
                identity_manager=SpeakerIdentityManager(config=identity_cfg),
                voice_emotion_cache=self._voice_cache,
                short_segment_threshold_sec=float(gp("short_segment_threshold_sec").double_value),
                max_bearing_delta_deg=float(gp("max_bearing_delta_deg").double_value),
            )
            self._privacy_mode = bool(gp("privacy_mode").bool_value)
            self.get_logger().info("SpeakerIntelligenceNode: configured")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_configure failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("SpeakerIntelligenceNode: activating …")
        try:
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value

            self._sub_transcription = self.create_subscription(
                SpeechTranscription,
                "/speech/transcription",
                self._cb_transcription,
                _QOS_RELIABLE,
            )
            self._sub_voice_emotion = self.create_subscription(
                VoiceEmotion,
                "/bonbon/affective/voice_emotion",
                self._cb_voice_emotion,
                _QOS_RELIABLE,
            )
            self._sub_person_tracks = self.create_subscription(
                PersonTrack,
                "/bonbon/persons/tracks",
                self._cb_person_track,
                _QOS_RELIABLE,
            )
            self._sub_safety = self.create_subscription(
                SafetyState,
                "/bonbon/safety/state",
                self._cb_safety,
                _QOS_TRANSIENT,
            )

            self._pub_turns = self.create_lifecycle_publisher(
                SpeakerTurn,
                "/bonbon/speaker/turns",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/speaker/speaker_intelligence_node/health",
                _QOS_RELIABLE,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("SpeakerIntelligenceNode: active")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_activate failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("SpeakerIntelligenceNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("SpeakerIntelligenceNode: cleaning up …")
        self._builder = None
        self._voice_cache = None
        self._person_bearings = []
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("SpeakerIntelligenceNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_voice_emotion(self, msg: VoiceEmotion) -> None:
        if self._voice_cache is not None:
            self._voice_cache.update(msg.dominant_emotion, msg.dominant_confidence)

    def _cb_person_track(self, msg: PersonTrack) -> None:
        if msg.lifecycle_state == "left_scene":
            self._person_bearings = [
                p for p in self._person_bearings if p.person_track_id != msg.person_track_id
            ]
            return
        bearing = _bearing_deg_from_xy(msg.position_3d.x, msg.position_3d.y)
        self._person_bearings = [
            p for p in self._person_bearings if p.person_track_id != msg.person_track_id
        ]
        self._person_bearings.append(TrackedPersonBearing(msg.person_track_id, bearing))

    def _cb_safety(self, msg: SafetyState) -> None:
        pass  # reserved; this node does not gate on safety state

    def _cb_transcription(self, msg: SpeechTranscription) -> None:
        if self._builder is None:
            return
        cycle_start = time.monotonic()
        try:
            self._process_transcription(msg)
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error("Speaker turn build failed: %s", str(exc))
        finally:
            _ = time.monotonic() - cycle_start

    def _process_transcription(self, msg: SpeechTranscription) -> None:
        segments = [
            DiarizationSegment(sid, start, end, conf)
            for sid, start, end, conf in zip(
                msg.segment_speaker_ids,
                msg.segment_start_sec,
                msg.segment_end_sec,
                msg.segment_confidences,
            )
        ]
        words = [
            WordTiming(w, s, e, c)
            for w, s, e, c in zip(
                msg.words, msg.word_start_times_sec, msg.word_end_times_sec, msg.word_confidences
            )
        ]
        if not segments:
            # No diarization detail available (diarizer disabled/timed out) —
            # fall back to a single synthetic segment spanning the whole
            # utterance so a turn is still produced for the primary speaker.
            segments = [
                DiarizationSegment(msg.speaker_id or "SPEAKER_00", 0.0, msg.audio_duration_sec)
            ]

        turns = self._builder.build_turns(
            segments=segments,
            words=words,
            full_text=msg.text,
            full_text_confidence=msg.confidence,
            doa_deg=msg.doa_angle_deg,
            tracked_persons=list(self._person_bearings),
            noisy_audio=msg.confidence < 0.3 and bool(msg.text) is False,
        )

        stamp = msg.header.stamp
        for turn in turns:
            self._pub_turns.publish(self._to_ros(turn, stamp))

    # ── Message construction ─────────────────────────────────────────────────

    def _to_ros(self, turn, stamp) -> SpeakerTurn:
        out = SpeakerTurn()
        out.header = Header()
        out.header.stamp = stamp
        out.header.frame_id = "map"
        out.speaker_id = turn.speaker_id
        out.person_track_id = "" if self._privacy_mode else turn.person_track_id
        out.association_confidence = float(turn.association_confidence)
        out.start_time = _offset_stamp(stamp, turn.start_time_sec)
        out.end_time = _offset_stamp(stamp, turn.end_time_sec)
        out.transcript = turn.transcript
        out.transcript_confidence = float(turn.transcript_confidence)
        out.voice_emotion = turn.voice_emotion
        out.emotion_confidence = float(turn.emotion_confidence)
        out.audio_source_direction_deg = float(turn.audio_source_direction_deg)
        out.is_new_speaker = turn.is_new_speaker
        out.is_overlapping = turn.is_overlapping
        out.is_off_camera = turn.is_off_camera
        out.noisy_audio = turn.noisy_audio
        out.short_segment = turn.short_segment
        return out

    # ── Health ───────────────────────────────────────────────────────────────

    def _health_status(self) -> tuple:
        now = time.monotonic()
        if self._last_cycle_t and (now - self._last_cycle_t) > 10.0:
            return _HEALTH_STALE, "no transcription processed recently"
        if self._error_count > 0 and self._cycle_count == 0:
            return _HEALTH_ERROR, "all cycles failing"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} cycle error(s)"
        if self._builder is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, (
            f"nominal (diarization_ambiguous_rate="
            f"{self._builder.diarization_ambiguous_rate:.2f})"
        )

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_speaker_intelligence.speaker_intelligence_node"
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
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None
        for attr in (
            "_sub_transcription",
            "_sub_voice_emotion",
            "_sub_person_tracks",
            "_sub_safety",
            "_pub_turns",
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
    node = SpeakerIntelligenceNode("speaker_intelligence_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
