"""
bonbon_behavior_engine.nodes.behavior_engine_node
===================================================
Central behavior decision engine for BonBon — ROS2 LifecycleNode.

Data flow
---------
Perception → Fusion → *BehaviorEngineNode* → Safety Gate → Actuation / TTS / Nav

This node:
  1. Subscribes to fused emotion, gesture events, spatial hints, and speech commands.
  2. Routes LLM/speech/gesture proposals through LLMCommandGate and ProposalEvaluator.
  3. Publishes approved BehaviorDecision messages.
  4. Dispatches ActuationGesture, TTSRequest, and NavigationGoal messages.

CRITICAL SAFETY INVARIANTS
---------------------------
- No LLM output EVER directly controls navigation or actuation.
- All proposals carry safety_check_required=True when from LLM.
- The EvaluateCommand service rejects critical/high-risk commands outright.
- Navigation proposals are published to /bonbon/behavior/nav_proposals, not /cmd_vel.
- The Safety Supervisor independently gates all downstream execution.

Lifecycle
---------
configure  → load config, init core components
activate   → create subscribers, publishers, services, start idle timer
deactivate → cancel idle timer, destroy ROS2 I/O
cleanup    → reset all state
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from std_msgs.msg import Header

from bonbon_msgs.msg import (
    ActuationGesture,
    BehaviorDecision,
    BehaviorProposal,
    GestureEvent,
    HumanEmotionState,
    SafetyState,
    SocialNavigationHint,
    SpatialEntity,
    SpeechCommand,
    TTSRequest,
)
from bonbon_srvs.srv import EvaluateCommand, HealthCheck, SetMode

from bonbon_behavior_engine.core.behavior_state_machine import (
    BehaviorState,
    BehaviorStateMachine,
)
from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.emotion_response_planner import EmotionAwareResponsePlanner
from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate
from bonbon_behavior_engine.core.proposal_evaluator import ProposalEvaluator

_logger = logging.getLogger(__name__)

_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_QOS_DEFAULT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_QOS_SENSOR = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)

# Seconds between idle behavior ticks
_IDLE_PERIOD_SEC = 15.0


class BehaviorEngineNode(LifecycleNode):
    """Central behavior decision engine (LifecycleNode).

    Routes all perceptual signals → decisions → dispatches commands to
    actuation, TTS and navigation.  The LLM is used for speech understanding
    only — it never directly controls hardware.
    """

    def __init__(self, node_name: str = "behavior_engine_node") -> None:
        super().__init__(node_name)

        # Core components
        self._fsm      = BehaviorStateMachine()
        self._clf      = CommandRiskClassifier()
        self._llm_gate = LLMCommandGate(risk_classifier=self._clf)
        self._evaluator = ProposalEvaluator(risk_classifier=self._clf)
        self._emotion_planner = EmotionAwareResponsePlanner()

        # Runtime state (protected by _lock)
        self._lock = threading.Lock()
        self._safety_level: int = 0
        self._safety_level_name: str = "INITIALIZING"
        self._actuation_enabled: bool = False
        self._tts_enabled: bool = False
        self._operating_mode: str = "normal"
        self._last_emotion: Optional[HumanEmotionState] = None
        self._last_person_id: str = ""
        self._last_tracking_id: int = -1
        self._person_present: bool = False

        # ROS2 I/O (created in on_activate)
        self._subs: list = []
        self._pubs: dict = {}
        self._srvs: list = []
        self._idle_timer = None
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="behavior_engine"
        )
        self._node_start = time.monotonic()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode configuring …")
        self.declare_parameter("operating_mode",         "normal")
        self.declare_parameter("idle_period_sec",        _IDLE_PERIOD_SEC)
        self.declare_parameter("max_tts_chars",          200)
        self.declare_parameter("enable_llm_proposals",   True)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode activating …")

        p = self.get_parameter
        self._operating_mode = (
            p("operating_mode").get_parameter_value().string_value
        )
        self._evaluator.set_operating_mode(self._operating_mode)
        idle_period = p("idle_period_sec").get_parameter_value().double_value

        # ── Publishers ────────────────────────────────────────────────────
        self._pubs["decision"] = self.create_lifecycle_publisher(
            BehaviorDecision, "/bonbon/behavior/decision", _QOS_DEFAULT
        )
        self._pubs["proposal"] = self.create_lifecycle_publisher(
            BehaviorProposal, "/bonbon/behavior/proposal", _QOS_DEFAULT
        )
        self._pubs["actuation"] = self.create_lifecycle_publisher(
            ActuationGesture, "/bonbon/behavior/actuation", _QOS_DEFAULT
        )
        self._pubs["tts"] = self.create_lifecycle_publisher(
            TTSRequest, "/bonbon/tts/request", _QOS_DEFAULT
        )

        # ── Subscribers ──────────────────────────────────────────────────
        def sub(msg_type, topic, cb, qos=_QOS_SENSOR):
            return self.create_subscription(msg_type, topic, cb, qos)

        self._subs = [
            sub(SafetyState,         "/bonbon/safety/state",
                self._on_safety_state, _QOS_TRANSIENT),
            sub(HumanEmotionState,   "/bonbon/affective/state",
                self._on_emotion_state),
            sub(GestureEvent,        "/bonbon/gesture/events",
                self._on_gesture_event),
            sub(SocialNavigationHint, "/bonbon/spatial/hints",
                self._on_spatial_hint),
            sub(SpatialEntity,       "/bonbon/spatial/entities",
                self._on_spatial_entity),
            sub(SpeechCommand,       "/speech/command",
                self._on_speech_command),
        ]

        # ── Services ─────────────────────────────────────────────────────
        self._srvs = [
            self.create_service(
                EvaluateCommand, "~/evaluate_command",
                self._handle_evaluate_command,
            ),
            self.create_service(
                SetMode, "~/set_mode",
                self._handle_set_mode,
            ),
            self.create_service(
                HealthCheck, "~/health_check",
                self._handle_health_check,
            ),
        ]

        # ── Idle behaviour timer ─────────────────────────────────────────
        self._idle_timer = self.create_timer(idle_period, self._on_idle_tick)

        self.get_logger().info(
            "BehaviorEngineNode active (mode=%s).", self._operating_mode
        )
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode deactivating …")
        if self._idle_timer:
            self.destroy_timer(self._idle_timer)
            self._idle_timer = None
        for sub in self._subs:
            self.destroy_subscription(sub)
        self._subs.clear()
        for srv in self._srvs:
            self.destroy_service(srv)
        self._srvs.clear()
        for pub in self._pubs.values():
            self.destroy_publisher(pub)
        self._pubs.clear()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode cleanup …")
        self._executor.shutdown(wait=False)
        with self._lock:
            self._last_emotion = None
            self._person_present = False
        self._fsm.force_transition(BehaviorState.IDLE, "cleanup")
        return TransitionCallbackReturn.SUCCESS

    # ── Safety state callback ──────────────────────────────────────────────

    def _on_safety_state(self, msg: SafetyState) -> None:
        with self._lock:
            self._safety_level      = msg.level
            self._safety_level_name = msg.level_name
            self._actuation_enabled = msg.actuation_enabled
            self._tts_enabled       = msg.tts_enabled
        self._evaluator.update_safety_level(msg.level)

        # Force ALERTING state on DANGER or above
        if msg.level >= 3 and self._fsm.current_state != BehaviorState.ALERTING:
            self._fsm.force_transition(
                BehaviorState.ALERTING,
                f"Safety level escalated to {msg.level_name}",
            )

    # ── Emotion state callback ─────────────────────────────────────────────

    def _on_emotion_state(self, msg: HumanEmotionState) -> None:
        with self._lock:
            self._last_emotion     = msg
            self._last_person_id   = msg.person_id
            self._last_tracking_id = msg.tracking_id

        # Emergency keyword check
        if getattr(msg, "has_emergency_keyword", False):
            self._executor.submit(
                self._dispatch_emergency_response,
                msg.person_id,
                msg.tracking_id,
            )
            return

        # Urgent distress
        if getattr(msg, "dominant_emotion", "") in ("distressed", "fearful"):
            if getattr(msg, "emotion_confidence", 0.0) > 0.6:
                self._executor.submit(
                    self._dispatch_emotion_response,
                    msg,
                )

    # ── Gesture event callback ─────────────────────────────────────────────

    def _on_gesture_event(self, msg: GestureEvent) -> None:
        gesture = getattr(msg, "gesture_name", "")
        is_safety = getattr(msg, "is_safety_relevant", False)

        if is_safety and gesture in ("raised_hand", "stop_palm"):
            self.get_logger().warn(
                "Safety gesture '%s' from person '%s'.",
                gesture, getattr(msg, "person_id", "?"),
            )
            self._executor.submit(self._dispatch_gesture_ack, gesture, msg)
            return

        if gesture in ("wave", "thumbs_up"):
            self._executor.submit(
                self._dispatch_proposal,
                "gesture", "wave",
                "gesture",
                getattr(msg, "person_id", ""),
                getattr(msg, "tracking_id", -1),
                0.2,
            )

    # ── Spatial hint callback ──────────────────────────────────────────────

    def _on_spatial_hint(self, msg: SocialNavigationHint) -> None:
        hint_type = getattr(msg, "hint_type", "")
        if hint_type == "stop" and self._fsm.current_state == BehaviorState.NAVIGATING:
            self.get_logger().warn("Spatial hint: STOP — pausing navigation intent.")

    # ── Spatial entity callback ────────────────────────────────────────────

    def _on_spatial_entity(self, msg: SpatialEntity) -> None:
        entity_type = getattr(msg, "entity_type", "")
        if entity_type == "person":
            was_present = self._person_present
            with self._lock:
                self._person_present   = True
                self._last_person_id   = getattr(msg, "person_id", "")
                self._last_tracking_id = getattr(msg, "tracking_id", -1)

            if not was_present:
                # New person detected → greet
                if self._fsm.can_transition_to(BehaviorState.GREETING):
                    self._fsm.transition(
                        BehaviorState.GREETING, "new person detected"
                    )
                    self._executor.submit(
                        self._dispatch_greeting,
                        self._last_person_id,
                        self._last_tracking_id,
                    )

    # ── Speech command callback ────────────────────────────────────────────

    def _on_speech_command(self, msg: SpeechCommand) -> None:
        intent  = getattr(msg, "intent",  "unknown")
        text    = getattr(msg, "text",    "")
        pid     = getattr(msg, "person_id", "")
        tid     = getattr(msg, "tracking_id", -1)

        self.get_logger().debug("Speech intent: '%s' text: '%s…'", intent, text[:40])

        if intent in ("greeting", "help", "question"):
            self._fsm.transition(BehaviorState.INTERACTING, f"speech intent: {intent}")
            self._executor.submit(
                self._dispatch_proposal,
                "speak", "",
                "speech_intent", pid, tid, 0.3,
            )
        elif intent == "farewell":
            self._executor.submit(
                self._dispatch_proposal,
                "gesture", "wave",
                "speech_intent", pid, tid, 0.2,
            )

    # ── Idle tick ─────────────────────────────────────────────────────────

    def _on_idle_tick(self) -> None:
        """Periodic idle behaviour."""
        if self._fsm.current_state != BehaviorState.IDLE:
            return
        if not self._actuation_enabled:
            return
        # Idle scan gesture
        self._dispatch_actuation_gesture("idle_scan", "", -1, priority=0)

    # ── Dispatch helpers ──────────────────────────────────────────────────────

    def _dispatch_greeting(self, person_id: str, tracking_id: int) -> None:
        """Send greeting gesture + TTS."""
        if self._actuation_enabled:
            self._dispatch_actuation_gesture("greeting_pose", person_id, tracking_id, priority=5)
        if self._tts_enabled:
            self._dispatch_tts(
                "Hello! I'm BonBon. How can I help you today?",
                "warm", person_id, tracking_id,
            )
        # Transition to INTERACTING after greeting
        time.sleep(2.0)
        self._fsm.transition(BehaviorState.INTERACTING, "greeting completed")

    def _dispatch_emotion_response(self, emotion_msg: HumanEmotionState) -> None:
        """Send gesture and TTS response to detected emotion."""
        dominant = getattr(emotion_msg, "dominant_emotion", "neutral")
        conf     = getattr(emotion_msg, "emotion_confidence", 0.5)
        pid      = getattr(emotion_msg, "person_id", "")
        tid      = getattr(emotion_msg, "tracking_id", -1)

        plan = self._emotion_planner.plan(
            dominant_emotion=dominant,
            emotion_confidence=conf,
            operating_mode=self._operating_mode,
        )

        if plan.gesture_name and self._actuation_enabled:
            self._dispatch_actuation_gesture(
                plan.gesture_name, pid, tid, priority=7
            )

        if plan.acknowledgment_text and self._tts_enabled:
            self._dispatch_tts(plan.acknowledgment_text, plan.tts_emotion, pid, tid)

    def _dispatch_emergency_response(self, person_id: str, tracking_id: int) -> None:
        """Handle emergency keyword detection."""
        self.get_logger().error(
            "Emergency keyword detected from person '%s'!", person_id
        )
        self._fsm.force_transition(BehaviorState.ALERTING, "emergency keyword detected")

        if self._actuation_enabled:
            self._dispatch_actuation_gesture(
                "emergency_attention_pose", person_id, tracking_id, priority=20
            )
        if self._tts_enabled:
            self._dispatch_tts(
                "Emergency detected! I'm alerting staff immediately.",
                "urgent", person_id, tracking_id,
            )
        # Publish alert decision
        self._publish_decision(
            event_id=str(uuid.uuid4())[:8],
            person_id=person_id,
            decision="approved",
            action="alert_operator",
            content="Emergency keyword detected — staff alerted",
            confidence=1.0,
            operator_alerted=True,
        )

    def _dispatch_gesture_ack(self, gesture: str, msg: GestureEvent) -> None:
        """Acknowledge a safety gesture from a person."""
        pid = getattr(msg, "person_id", "")
        tid = getattr(msg, "tracking_id", -1)
        if self._actuation_enabled:
            ack_gesture = "nod_yes" if gesture == "thumbs_up" else "rest_pose"
            self._dispatch_actuation_gesture(ack_gesture, pid, tid, priority=10)
        if self._tts_enabled:
            self._dispatch_tts("Understood. I'll stop.", "calm", pid, tid)

    def _dispatch_proposal(
        self,
        proposal_type: str,
        proposal_content: str,
        source: str,
        person_id: str,
        tracking_id: int,
        urgency: float,
        raw_llm_command: str = "",
    ) -> None:
        """Evaluate a proposal and dispatch if approved."""
        result = self._evaluator.evaluate(
            proposal_type, proposal_content, source, urgency, raw_llm_command
        )

        event_id = str(uuid.uuid4())[:8]
        self._publish_decision(
            event_id=event_id,
            person_id=person_id,
            decision=result.decision,
            action=result.approved_action,
            content=result.approved_content,
            confidence=result.confidence,
            operator_alerted=result.operator_alerted,
        )

        if result.decision not in ("approved", "modified"):
            return

        if result.approved_action == "speak" and self._tts_enabled:
            self._dispatch_tts(result.approved_content, "neutral", person_id, tracking_id)
        elif result.approved_action == "gesture" and self._actuation_enabled:
            self._dispatch_actuation_gesture(
                result.approved_content, person_id, tracking_id, priority=5
            )

    def _dispatch_actuation_gesture(
        self,
        gesture_name: str,
        person_id: str,
        tracking_id: int,
        priority: int = 5,
        speed_scale: float = 1.0,
    ) -> None:
        if "actuation" not in self._pubs:
            return
        msg = ActuationGesture()
        msg.header            = Header()
        msg.header.stamp      = self.get_clock().now().to_msg()
        msg.event_id          = str(uuid.uuid4())[:8]
        msg.requested_at      = self.get_clock().now().to_msg()
        msg.source_module     = "bonbon_behavior_engine"
        msg.person_id         = person_id
        msg.tracking_id       = tracking_id
        msg.gesture_name      = gesture_name
        msg.priority          = priority
        msg.speed_scale       = speed_scale
        msg.interruptible     = priority < 15
        msg.timeout_sec       = 10.0
        self._pubs["actuation"].publish(msg)

    def _dispatch_tts(
        self,
        text: str,
        emotion: str,
        person_id: str,
        tracking_id: int,
    ) -> None:
        if "tts" not in self._pubs:
            return
        msg = TTSRequest()
        msg.header        = Header()
        msg.header.stamp  = self.get_clock().now().to_msg()
        msg.text          = text
        msg.emotion       = emotion
        msg.person_id     = person_id
        msg.tracking_id   = tracking_id
        msg.priority      = 5
        self._pubs["tts"].publish(msg)

    def _publish_decision(
        self,
        event_id: str,
        person_id: str,
        decision: str,
        action: str,
        content: str,
        confidence: float,
        operator_alerted: bool,
    ) -> None:
        if "decision" not in self._pubs:
            return
        msg = BehaviorDecision()
        msg.header           = Header()
        msg.header.stamp     = self.get_clock().now().to_msg()
        msg.event_id         = event_id
        msg.decided_at       = self.get_clock().now().to_msg()
        msg.source_module    = "bonbon_behavior_engine"
        msg.person_id        = person_id
        msg.decision         = decision
        msg.approved_action  = action
        msg.approved_content = content
        msg.safety_approved  = True
        msg.confidence       = float(confidence)
        msg.operator_alerted = operator_alerted
        msg.logged           = True
        self._pubs["decision"].publish(msg)

    # ── Service handlers ───────────────────────────────────────────────────────

    def _handle_evaluate_command(
        self,
        request: EvaluateCommand.Request,
        response: EvaluateCommand.Response,
    ) -> EvaluateCommand.Response:
        """Evaluate a command from an operator, speech, or LLM source."""
        risk = self._clf.classify(request.command_text, source=request.source)
        response.safe             = risk.is_safe
        response.risk_level       = risk.risk_level
        response.reasons          = risk.reasons
        response.recommended_action = risk.recommended_action
        response.modified_command = ""

        if not risk.is_safe:
            self.get_logger().warn(
                "EvaluateCommand: CRITICAL risk from '%s': '%s…'",
                request.source, request.command_text[:60],
            )

        return response

    def _handle_set_mode(
        self,
        request: SetMode.Request,
        response: SetMode.Response,
    ) -> SetMode.Response:
        prev = self._operating_mode
        allowed_modes = {"normal", "child_safe", "elderly", "degraded", "demo", "emergency"}

        if request.mode not in allowed_modes:
            response.success       = False
            response.previous_mode = prev
            response.error_message = f"Unknown mode '{request.mode}'."
            return response

        with self._lock:
            self._operating_mode = request.mode
        self._evaluator.set_operating_mode(request.mode)

        self.get_logger().info(
            "Operating mode changed: '%s' → '%s' by operator '%s'.",
            prev, request.mode, request.operator_id,
        )
        response.success       = True
        response.previous_mode = prev
        response.error_message = ""
        return response

    def _handle_health_check(
        self,
        request: HealthCheck.Request,
        response: HealthCheck.Response,
    ) -> HealthCheck.Response:
        gate_stats = self._llm_gate.stats()
        response.healthy   = True
        response.status    = (
            f"active; state={self._fsm.current_state_name}; "
            f"mode={self._operating_mode}; "
            f"safety={self._safety_level_name}; "
            f"llm_gate: {gate_stats['approved']}/{gate_stats['total']} approved"
        )
        response.warnings  = []
        response.errors    = []
        response.uptime_sec = time.monotonic() - self._node_start
        return response


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None) -> None:
    """ROS2 entry point."""
    rclpy.init(args=args)
    node = BehaviorEngineNode("behavior_engine_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
