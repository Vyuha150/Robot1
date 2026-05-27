"""
bonbon_perception_ai.nodes.perception_node
==========================================
ROS2 LifecycleNode — Perception + AI pipeline.

Subscriptions
-------------
/bonbon/vision/objects      DetectedObjectArray   (10 Hz)
/bonbon/vision/persons      PersonStateArray      (10 Hz)
/speech/command             SpeechCommand         (event)
/bonbon/nav/status          (std_msgs/String)     (2 Hz)   [optional]
/bonbon/spatial/pose        (geometry_msgs/Pose2D)(5 Hz)   [optional]

Publications
------------
/perception/scene           SemanticScene         (≤10 Hz)
/perception/intent          UserIntent            (on speech)
/perception/events          ContextEvent          (on change)
/perception/risks           RiskEvent             (on detection)
/perception/behavior        BehaviorRecommendation(on intent/risk)
/perception/memory_updates  MemoryEntry           (on record)
/health/perception_ai       ModuleHealth          (1 Hz)

Lifecycle
---------
unconfigured → on_configure → inactive
inactive     → on_activate  → active   ← pipeline timer starts
active       → on_deactivate→ inactive
inactive     → on_cleanup   → unconfigured
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

logger = logging.getLogger(__name__)


class PerceptionAINode(LifecycleNode):
    """Fuses sensor inputs into semantic scene understanding."""

    _HEALTH_OK = 0
    _HEALTH_WARN = 1
    _HEALTH_ERROR = 2

    def __init__(self, node_name: str = "perception_ai_node") -> None:
        super().__init__(node_name)

        # Pipeline components — set in on_configure
        self._cfg = None
        self._fusion = None
        self._scene_an = None
        self._intent_eng = None
        self._risk_assr = None
        self._behavior_rc = None
        self._memory = None

        # Publishers / subscribers / timers
        self._pub_scene = None
        self._pub_intent = None
        self._pub_events = None
        self._pub_risks = None
        self._pub_behavior = None
        self._pub_memory = None
        self._pub_health = None

        self._scene_timer = None
        self._health_timer = None
        self._pipeline_ok = False
        self._error_msg = ""
        self._start_time = time.monotonic()
        self._scene_count = 0
        self._lock = threading.Lock()

        self.get_logger().info("PerceptionAINode created")

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
                self.get_logger().warning("degraded startup allowed — continuing")
                return TransitionCallbackReturn.SUCCESS
            return TransitionCallbackReturn.FAILURE

    def _load_config(self) -> None:
        from bonbon_perception_ai.config.perception_config import PerceptionAIConfig

        self._cfg = PerceptionAIConfig.from_ros_params(self)
        self._cfg.validate()

    def _create_interfaces(self) -> None:
        from bonbon_msgs.msg import (  # type: ignore
            BehaviorRecommendation,
            ContextEvent,
            DetectedObjectArray,
            MemoryEntry,
            ModuleHealth,
            PersonStateArray,
            RiskEvent,
            SemanticScene,
            SpeechCommand,
            UserIntent,
        )

        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        best_effort = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # Publishers
        self._pub_scene = self.create_lifecycle_publisher(
            SemanticScene, "/perception/scene", reliable_qos
        )
        self._pub_intent = self.create_lifecycle_publisher(
            UserIntent, "/perception/intent", reliable_qos
        )
        self._pub_events = self.create_lifecycle_publisher(
            ContextEvent, "/perception/events", reliable_qos
        )
        self._pub_risks = self.create_lifecycle_publisher(
            RiskEvent, "/perception/risks", reliable_qos
        )
        self._pub_behavior = self.create_lifecycle_publisher(
            BehaviorRecommendation, "/perception/behavior", reliable_qos
        )
        self._pub_memory = self.create_lifecycle_publisher(
            MemoryEntry, "/perception/memory_updates", reliable_qos
        )
        self._pub_health = self.create_lifecycle_publisher(
            ModuleHealth, "/health/perception_ai", reliable_qos
        )

        # Subscriptions
        self.create_subscription(
            DetectedObjectArray, "/bonbon/vision/objects", self._on_objects, best_effort
        )
        self.create_subscription(
            PersonStateArray, "/bonbon/vision/persons", self._on_persons, best_effort
        )
        self.create_subscription(SpeechCommand, "/speech/command", self._on_speech, reliable_qos)

    def _init_pipeline(self) -> None:
        from bonbon_perception_ai.fusion.multimodal_fusion import MultimodalFusion
        from bonbon_perception_ai.memory.memory_manager import MemoryManager
        from bonbon_perception_ai.understanding.behavior_recommender import BehaviorRecommender
        from bonbon_perception_ai.understanding.intent_engine import IntentEngine
        from bonbon_perception_ai.understanding.risk_assessor import RiskAssessor
        from bonbon_perception_ai.understanding.scene_analyzer import SceneAnalyzer

        cfg = self._cfg
        self._fusion = MultimodalFusion(cfg.fusion)
        self._scene_an = SceneAnalyzer(cfg.scene)
        self._intent_eng = IntentEngine(cfg.intent)
        self._risk_assr = RiskAssessor(cfg.risk)
        self._behavior_rc = BehaviorRecommender()

        self._memory = MemoryManager(cfg.memory)
        try:
            self._memory.open()
        except Exception as exc:
            self.get_logger().warning(f"Memory open failed (non-fatal): {exc}")
            self._memory = None

    # ── Lifecycle: activate / deactivate / cleanup ────────────────────────────

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_activate")
        period = 1.0 / max(self._cfg.scene_publish_rate_hz, 0.1)
        self._scene_timer = self.create_timer(period, self._on_scene_tick)
        self._health_timer = self.create_timer(
            1.0 / max(self._cfg.health_rate_hz, 0.1),
            self._publish_health,
        )
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_deactivate")
        for t in (self._scene_timer, self._health_timer):
            if t:
                t.cancel()
        self._scene_timer = self._health_timer = None
        if self._fusion:
            self._fusion.clear_all()
        if self._scene_an:
            self._scene_an.reset()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("on_cleanup")
        if self._memory:
            self._memory.close()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        if self._memory:
            self._memory.close()
        return TransitionCallbackReturn.SUCCESS

    # ── ROS2 subscription callbacks ───────────────────────────────────────────

    def _on_objects(self, msg) -> None:
        from bonbon_perception_ai.fusion.types import ObjectObservation

        try:
            objects = [
                ObjectObservation(
                    class_name=o.class_name,
                    confidence=float(o.confidence),
                    distance_m=float(o.depth_m) if not math.isnan(float(o.depth_m)) else math.nan,
                    bearing_deg=float(o.bearing_deg),
                    track_id=str(o.track_id),
                )
                for o in msg.objects
            ]
            self._fusion.update_objects(objects)
        except Exception as exc:
            self.get_logger().debug(f"_on_objects error: {exc}")

    def _on_persons(self, msg) -> None:
        from bonbon_perception_ai.fusion.types import PersonObservation

        try:
            persons = [
                PersonObservation(
                    person_id=str(p.track_id),
                    confidence=0.90,  # PersonState has no confidence field
                    distance_m=float(p.distance_m),
                    bearing_deg=float(p.bearing_deg),
                    facing_robot=bool(p.facing_robot),
                    age_group=str(p.age_group),
                    face_id=str(p.face_id) if not self._cfg.privacy.suppress_speaker_id else "",
                    velocity_mps=float(p.velocity_mps),
                )
                for p in msg.persons
            ]
            self._fusion.update_persons(persons)
            # Record persons in memory
            if self._memory:
                for p in persons:
                    self._memory.record_person(p.person_id, face_id=p.face_id)
        except Exception as exc:
            self.get_logger().debug(f"_on_persons error: {exc}")

    def _on_speech(self, msg) -> None:
        from bonbon_perception_ai.fusion.types import SpeechInput

        try:
            speech = SpeechInput(
                text=str(msg.text),
                confidence=float(msg.confidence),
                speaker_id=str(msg.speaker_id),
                is_low_confidence=bool(msg.is_low_confidence),
                is_silence=bool(msg.is_silence),
                is_timeout=bool(msg.is_timeout),
                language=str(msg.language),
                doa_angle_deg=float(msg.doa_angle_deg),
            )
            self._fusion.update_speech(speech)

            # Classify intent immediately on speech arrival
            with self._lock:
                ctx = self._fusion.fuse()
                intent = self._intent_eng.classify(speech, ctx)

            if intent is None:
                return  # ambiguity_policy = "ignore"

            self._publish_intent(intent, msg.header)

            # Record in memory
            if self._memory and speech.speaker_id:
                self._memory.record_interaction(speech.speaker_id, intent)
                self._publish_memory_entry(
                    entry_type="person_interaction",
                    subject_id=speech.speaker_id,
                    keys=["intent_class", "raw_text"],
                    values=[intent.intent_class, intent.raw_text[:80]],
                    header=msg.header,
                )

            # Risk check for conflicting commands
            scene_snap, _ = self._scene_an.analyze(ctx)
            risks = self._risk_assr.assess(ctx, scene_snap, intent.intent_class)
            for r in risks:
                self._publish_risk(r, msg.header)

            # Behavior recommendation
            rec = self._behavior_rc.recommend(ctx, scene_snap, intent, risks)
            self._publish_behavior(rec, msg.header)

        except Exception as exc:
            self.get_logger().debug(f"_on_speech error: {exc}")

    # ── Scene timer callback ──────────────────────────────────────────────────

    def _on_scene_tick(self) -> None:
        if not self._pipeline_ok:
            return
        try:
            with self._lock:
                ctx = self._fusion.fuse()

            snap, events = self._scene_an.analyze(ctx)
            risks = self._risk_assr.assess(ctx, snap)
            rec = self._behavior_rc.recommend(ctx, snap, None, risks)

            self._publish_scene(snap)
            for ev in events:
                self._publish_context_event(ev)
            for r in risks:
                self._publish_risk(r)

            self._publish_behavior(rec)

            if self._memory:
                self._memory.record_scene(snap)

            self._scene_count += 1
        except Exception as exc:
            self.get_logger().debug(f"scene tick error: {exc}")

    # ── Publisher helpers ─────────────────────────────────────────────────────

    def _publish_scene(self, snap, header=None) -> None:
        try:
            from bonbon_msgs.msg import SemanticScene  # type: ignore

            msg = SemanticScene()
            msg.header = header
            msg.scene_id = snap.scene_id
            msg.confidence = float(snap.confidence)
            msg.uncertainty_level = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(
                snap.uncertainty_level, 1
            )
            msg.present_object_classes = list(snap.present_object_classes)
            msg.present_person_ids = list(snap.present_person_ids)
            msg.dominant_activity = {
                "idle": 0,
                "interacting": 1,
                "navigating": 2,
                "serving": 3,
                "crowded": 4,
            }.get(snap.dominant_activity, 0)
            msg.activity_label = snap.activity_label
            msg.spatial_context = snap.spatial_context
            msg.human_proximity_m = (
                float(snap.human_proximity_m) if snap.human_proximity_m != math.inf else -1.0
            )
            msg.is_crowded = snap.is_crowded
            msg.stale_modalities = list(snap.stale_modalities)
            msg.description = snap.description
            self._pub_scene.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_scene error: {exc}")

    def _publish_intent(self, intent, header=None) -> None:
        try:
            from bonbon_msgs.msg import UserIntent as UIMsg  # type: ignore

            msg = UIMsg()
            msg.header = header
            msg.intent_id = intent.intent_id
            msg.speaker_id = intent.speaker_id
            msg.intent_class = intent.intent_class
            msg.confidence = float(intent.confidence)
            msg.is_ambiguous = intent.is_ambiguous
            msg.fallback_response = intent.fallback_response
            msg.slot_names = [s.name for s in intent.slots]
            msg.slot_values = [s.value for s in intent.slots]
            msg.slot_confidences = [float(s.confidence) for s in intent.slots]
            msg.raw_text = intent.raw_text
            msg.speech_confidence = float(intent.speech_confidence)
            self._pub_intent.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_intent error: {exc}")

    def _publish_context_event(self, ev, header=None) -> None:
        try:
            from bonbon_msgs.msg import ContextEvent as CEMsg  # type: ignore

            msg = CEMsg()
            msg.header = header
            msg.event_id = ev.event_id
            msg.event_type = ev.event_type
            msg.confidence = float(ev.confidence)
            msg.subject_id = ev.subject_id
            msg.related_ids = list(ev.related_ids)
            msg.prior_value = ev.prior_value
            msg.new_value = ev.new_value
            msg.description = ev.description
            self._pub_events.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_event error: {exc}")

    def _publish_risk(self, risk, header=None) -> None:
        try:
            from bonbon_msgs.msg import RiskEvent as REMsg  # type: ignore

            sev_int = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}.get(
                risk.severity, 0
            )
            msg = REMsg()
            msg.header = header
            msg.risk_id = risk.risk_id
            msg.severity = sev_int
            msg.severity_label = risk.severity.lower()
            msg.risk_type = risk.risk_type
            msg.confidence = float(risk.confidence)
            msg.subject_id = risk.subject_id
            msg.distance_m = float(risk.distance_m)
            msg.description = risk.description
            msg.requires_immediate_action = risk.requires_immediate_action
            msg.suggested_action = risk.suggested_action
            self._pub_risks.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_risk error: {exc}")

    def _publish_behavior(self, rec, header=None) -> None:
        try:
            from bonbon_msgs.msg import BehaviorRecommendation as BRMsg  # type: ignore

            msg = BRMsg()
            msg.header = header
            msg.recommendation_id = rec.recommendation_id
            msg.behavior_class = rec.behavior_class
            msg.confidence = float(rec.confidence)
            msg.priority = rec.priority
            msg.trigger_type = rec.trigger_type
            msg.trigger_id = rec.trigger_id
            msg.param_names = list(rec.params.keys())
            msg.param_values = list(rec.params.values())
            msg.timeout_sec = float(rec.timeout_sec)
            self._pub_behavior.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_behavior error: {exc}")

    def _publish_memory_entry(
        self,
        entry_type: str,
        subject_id: str,
        keys: list,
        values: list,
        header=None,
        is_private: bool = False,
    ) -> None:
        try:
            from bonbon_msgs.msg import MemoryEntry as MEMsg  # type: ignore

            msg = MEMsg()
            msg.header = header
            msg.entry_id = str(uuid.uuid4())
            msg.entry_type = entry_type
            msg.subject_id = subject_id
            msg.key_names = list(keys)
            msg.key_values = [str(v) for v in values]
            msg.relevance_score = 0.7
            msg.is_private = is_private
            msg.expires_at_sec = 0.0
            self._pub_memory.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"publish_memory error: {exc}")

    def _publish_health(self) -> None:
        try:
            from bonbon_msgs.msg import ModuleHealth  # type: ignore

            uptime = time.monotonic() - self._start_time
            status = self._HEALTH_OK if self._pipeline_ok else self._HEALTH_ERROR
            msg = ModuleHealth()
            msg.module_name = "bonbon_perception_ai.perception_node"
            msg.status = status
            msg.status_text = self._cfg.summary() if self._pipeline_ok else self._error_msg
            msg.uptime_sec = float(uptime)
            msg.processed_count = self._scene_count
            msg.latency_ms = 0.0
            msg.error_count = 0
            self._pub_health.publish(msg)
        except Exception as exc:
            self.get_logger().debug(f"health publish error: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PerceptionAINode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
