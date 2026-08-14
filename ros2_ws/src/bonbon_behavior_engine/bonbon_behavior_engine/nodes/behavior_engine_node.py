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
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import rclpy
from bonbon_msgs.msg import (
    ActuationGesture,
    BehaviorDecision,
    BehaviorProposal,
    BehaviorRecommendation,
    GestureEvent,
    HumanEmotionState,
    HumanState,
    PersonTrack,
    RiskEvent,
    SafetyState,
    SocialNavigationHint,
    SpatialEntity,
    SpeechCommand,
    TTSRequest,
)
from bonbon_srvs.srv import EvaluateCommand, HealthCheck, SetMode
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header

from bonbon_behavior_engine.core.behavior_recommendation_bridge import (
    recommendation_to_proposal,
)
from bonbon_behavior_engine.core.behavior_state_machine import (
    BehaviorState,
    BehaviorStateMachine,
)
from bonbon_behavior_engine.core.command_risk_classifier import CommandRiskClassifier
from bonbon_behavior_engine.core.emotion_response_planner import EmotionAwareResponsePlanner
from bonbon_behavior_engine.core.llm_command_gate import LLMCommandGate
from bonbon_behavior_engine.core.multi_person_behavior_selector import (
    MultiPersonBehaviorSelector,
    apply_child_safety_modifier,
    select_focus_person,
)
from bonbon_behavior_engine.core.operator_alerter import OperatorAlerter
from bonbon_behavior_engine.core.proposal_evaluator import ProposalEvaluator
from bonbon_behavior_engine.core.spatial_response_planner import SpatialResponsePlanner

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
        self._fsm = BehaviorStateMachine()
        self._clf = CommandRiskClassifier()
        self._llm_gate = LLMCommandGate(risk_classifier=self._clf)
        self._evaluator = ProposalEvaluator(risk_classifier=self._clf)

        # Finding 8 fix (docs/SAFETY_SEPARATION_AUDIT.md): _dispatch_proposal
        # only ever ran ProposalEvaluator/CommandRiskClassifier -- and
        # CommandRiskClassifier is only actually invoked when
        # source=="llm" (see ProposalEvaluator.evaluate()), so gesture-
        # and speech-intent-sourced proposals (the majority of calls into
        # _dispatch_proposal) never had ANY content-risk screening at
        # all. SafetySeparationGuard is added here as an independent,
        # additional check -- defense-in-depth, not a replacement for
        # ProposalEvaluator or the real, tested, fail-closed
        # ActuationSafetyGate downstream of /bonbon/behavior/actuation.
        # Degrades to None (dispatch behaves exactly as before this fix)
        # if bonbon_edge_ai_runtime isn't installed.
        try:
            from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

            self._safety_guard = SafetySeparationGuard()
        except Exception as exc:  # noqa: BLE001 -- optional dependency, must never break the node
            self.get_logger().warning(
                f"safety_separation_guard unavailable ({exc}); Finding-8 defense-in-depth check disabled"
            )
            self._safety_guard = None
        self._emotion_planner = EmotionAwareResponsePlanner()
        self._spatial_planner = SpatialResponsePlanner()
        self._operator_alerter = OperatorAlerter()
        self._behavior_selector = MultiPersonBehaviorSelector()

        # Runtime state (protected by _lock)
        self._lock = threading.Lock()
        self._safety_level: int = 0
        self._safety_level_name: str = "INITIALIZING"
        self._actuation_enabled: bool = False
        self._tts_enabled: bool = False
        self._operating_mode: str = "normal"
        self._privacy_mode: bool = False
        self._last_emotion: HumanEmotionState | None = None
        self._last_person_id: str = ""
        self._last_tracking_id: int = -1
        self._person_present: bool = False

        # Multi-person state (bonbon_human_state_fusion / bonbon_multi_person_tracker)
        self._human_states: dict[str, HumanState] = {}
        self._person_track_raw_ids: dict[str, str] = {}  # person_track_id -> raw vision track_id
        self._person_categories: dict[str, str] = {}  # raw track_id -> 'child'|'adult'|...

        # ROS2 I/O (created in on_activate)
        self._subs: list = []
        self._pubs: dict = {}
        self._srvs: list = []
        self._idle_timer = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="behavior_engine")
        self._node_start = time.monotonic()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode configuring …")
        self.declare_parameter("operating_mode", "normal")
        self.declare_parameter("idle_period_sec", _IDLE_PERIOD_SEC)
        self.declare_parameter("max_tts_chars", 200)
        self.declare_parameter("enable_llm_proposals", True)
        self.declare_parameter("operator_alert_cooldown_sec", 10.0)
        self.declare_parameter("privacy_mode", False)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("BehaviorEngineNode activating …")

        p = self.get_parameter
        self._operating_mode = p("operating_mode").get_parameter_value().string_value
        self._evaluator.set_operating_mode(self._operating_mode)
        self._privacy_mode = p("privacy_mode").get_parameter_value().bool_value
        idle_period = p("idle_period_sec").get_parameter_value().double_value
        cooldown = p("operator_alert_cooldown_sec").get_parameter_value().double_value
        self._operator_alerter = OperatorAlerter(cooldown_sec=cooldown)

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
        # Operator-alert egress (consumed by bonbon_operator_api dashboard).
        self._pubs["operator_alert"] = self.create_lifecycle_publisher(
            RiskEvent, "/bonbon/operator/alerts", _QOS_DEFAULT
        )

        # ── Subscribers ──────────────────────────────────────────────────
        def sub(msg_type, topic, cb, qos=_QOS_SENSOR):
            return self.create_subscription(msg_type, topic, cb, qos)

        self._subs = [
            sub(SafetyState, "/bonbon/safety/state", self._on_safety_state, _QOS_TRANSIENT),
            sub(HumanEmotionState, "/bonbon/affective/human_state", self._on_emotion_state),
            sub(GestureEvent, "/bonbon/gesture/events", self._on_gesture_event),
            sub(SocialNavigationHint, "/bonbon/spatial/hints", self._on_spatial_hint),
            sub(SpatialEntity, "/bonbon/spatial/entities", self._on_spatial_entity),
            sub(RiskEvent, "/bonbon/spatial/alerts", self._on_spatial_alert, _QOS_DEFAULT),
            sub(SpeechCommand, "/speech/command", self._on_speech_command),
            sub(HumanState, "/bonbon/human/state", self._on_human_state),
            sub(PersonTrack, "/bonbon/persons/tracks", self._on_person_track),
            sub(
                BehaviorRecommendation,
                "/perception/behavior",
                self._on_behavior_recommendation,
                _QOS_DEFAULT,
            ),
        ]

        # ── Services ─────────────────────────────────────────────────────
        self._srvs = [
            self.create_service(
                EvaluateCommand,
                "~/evaluate_command",
                self._handle_evaluate_command,
            ),
            self.create_service(
                SetMode,
                "~/set_mode",
                self._handle_set_mode,
            ),
            self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            ),
        ]

        # ── Idle behaviour timer ─────────────────────────────────────────
        self._idle_timer = self.create_timer(idle_period, self._on_idle_tick)

        self.get_logger().info(f"BehaviorEngineNode active (mode={self._operating_mode}).")
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
            self._human_states.clear()
            self._person_track_raw_ids.clear()
            self._person_categories.clear()
        self._behavior_selector = MultiPersonBehaviorSelector()
        self._operator_alerter.reset()
        self._fsm.force_transition(BehaviorState.IDLE, "cleanup")
        return TransitionCallbackReturn.SUCCESS

    # ── Safety state callback ──────────────────────────────────────────────

    def _on_safety_state(self, msg: SafetyState) -> None:
        with self._lock:
            self._safety_level = msg.level
            self._safety_level_name = msg.level_name
            self._actuation_enabled = msg.actuation_enabled
            self._tts_enabled = msg.tts_enabled
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
            self._last_emotion = msg
            self._last_person_id = msg.person_id
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
                f"Safety gesture '{gesture}' from person '{getattr(msg, 'person_id', '?')}'."
            )
            self._executor.submit(self._dispatch_gesture_ack, gesture, msg)
            return

        if gesture in ("wave", "thumbs_up"):
            self._executor.submit(
                self._dispatch_proposal,
                "gesture",
                "wave",
                "gesture",
                getattr(msg, "person_id", ""),
                getattr(msg, "tracking_id", -1),
                0.2,
            )

    # ── Spatial hint callback ──────────────────────────────────────────────

    def _on_spatial_hint(self, msg: SocialNavigationHint) -> None:
        hint_type = getattr(msg, "hint_type", "")
        urgency = float(getattr(msg, "urgency", 0.0))
        response = self._spatial_planner.plan_for_hint(hint_type, urgency)
        self._executor.submit(self._apply_spatial_response, response, "scene")

    # ── Spatial alert callback (RiskEvent from bonbon_spatial) ──────────────

    def _on_spatial_alert(self, msg: RiskEvent) -> None:
        risk_type = getattr(msg, "risk_type", "")
        severity = int(getattr(msg, "severity", 2))
        subject = getattr(msg, "subject_id", "") or "scene"
        response = self._spatial_planner.plan_for_alert(risk_type, severity)
        self.get_logger().info(f"Spatial alert '{risk_type}' (sev={severity}) → {response.reason}")
        self._executor.submit(self._apply_spatial_response, response, subject)

    def _apply_spatial_response(self, response, subject_id: str) -> None:
        """Execute a SpatialResponse via the normal safety-gated dispatch path."""
        if response.pause_navigation and self._fsm.current_state == BehaviorState.NAVIGATING:
            self.get_logger().warn(f"Spatial response: pausing navigation ({response.reason})")
            # Pause is advisory here; navigation node enforces its own safety stop.

        if response.gesture and self._actuation_enabled:
            self._dispatch_actuation_gesture(
                response.gesture,
                self._last_person_id,
                self._last_tracking_id,
                priority=response.gesture_priority,
            )

        if response.say and self._tts_enabled:
            self._dispatch_tts(
                response.say, response.tts_emotion, self._last_person_id, self._last_tracking_id
            )

        if response.escalate_to_operator:
            self._raise_operator_alert(
                alert_type="spatial",
                severity=response.operator_severity,
                subject_id=subject_id,
                description=response.reason,
            )

    def _raise_operator_alert(
        self, alert_type: str, severity: int, subject_id: str, description: str
    ) -> None:
        """Deduplicate then publish an operator alert as a RiskEvent."""
        decision = self._operator_alerter.request(
            alert_type=alert_type,
            severity=severity,
            subject_id=subject_id,
            description=description,
        )
        if not decision.should_send:
            self.get_logger().debug(f"Operator alert suppressed: {decision.suppressed_reason}")
            return
        pub = self._pubs.get("operator_alert")
        if pub is None:
            return
        msg = RiskEvent()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "behavior_engine"
        msg.risk_id = str(uuid.uuid4())[:8]
        msg.severity = decision.severity
        msg.severity_label = decision.severity_label
        msg.risk_type = decision.alert_type
        msg.confidence = 1.0
        msg.subject_id = decision.subject_id
        msg.distance_m = -1.0
        msg.description = decision.description
        msg.requires_immediate_action = decision.severity >= 3
        msg.suggested_action = "notify_operator"
        pub.publish(msg)

    # ── Spatial entity callback ────────────────────────────────────────────

    def _on_spatial_entity(self, msg: SpatialEntity) -> None:
        entity_type = getattr(msg, "entity_type", "")
        if entity_type == "person":
            was_present = self._person_present
            person_id = getattr(msg, "person_id", "")
            with self._lock:
                self._person_present = True
                self._last_person_id = person_id
                self._last_tracking_id = getattr(msg, "tracking_id", -1)
                # Bridges bonbon_human_state_fusion's person_track_id (via
                # raw_track_id, cached in _on_person_track) to SpatialEntity's
                # person_category — used by rule 9 (child safety modifier).
                if person_id:
                    self._person_categories[person_id] = getattr(msg, "person_category", "unknown")

            if not was_present:
                # New person detected → greet
                if self._fsm.can_transition_to(BehaviorState.GREETING):
                    self._fsm.transition(BehaviorState.GREETING, "new person detected")
                    self._executor.submit(
                        self._dispatch_greeting,
                        self._last_person_id,
                        self._last_tracking_id,
                    )

    # ── Speech command callback ────────────────────────────────────────────

    def _on_speech_command(self, msg: SpeechCommand) -> None:
        intent = getattr(msg, "intent", "unknown")
        text = getattr(msg, "text", "")
        pid = getattr(msg, "person_id", "")
        tid = getattr(msg, "tracking_id", -1)

        self.get_logger().debug(f"Speech intent: '{intent}' text: '{text[:40]}…'")

        if intent in ("greeting", "help", "question"):
            self._fsm.transition(BehaviorState.INTERACTING, f"speech intent: {intent}")
            self._executor.submit(
                self._dispatch_proposal,
                "speak",
                "",
                "speech_intent",
                pid,
                tid,
                0.3,
            )
        elif intent == "farewell":
            self._executor.submit(
                self._dispatch_proposal,
                "gesture",
                "wave",
                "speech_intent",
                pid,
                tid,
                0.2,
            )

    # ── Behavior recommendation bridge (GAP-E2 fix) ──────────────────────────

    def _on_behavior_recommendation(self, msg: BehaviorRecommendation) -> None:
        """Forwards a navigation-relevant BehaviorRecommendation (from
        bonbon_perception_ai or bonbon_llm.llm_orchestrator_node) to
        bonbon_motion_approval_gateway as a real BehaviorProposal --
        previously nothing did this, so bonbon_navigation's own direct
        subscription to /perception/behavior was the ONLY thing acting
        on these messages, with no approval step at all (GAP-E1/E2, see
        docs/SAFETY_SEPARATION_AUDIT.md). This node's BehaviorProposal
        publisher already existed (self._pubs["proposal"]) but was never
        called until this handler.

        stop_navigation and other non-navigation behavior classes are
        deliberately NOT bridged here -- recommendation_to_proposal()
        returns None for them, and bonbon_navigation still handles
        stop_navigation directly (a cancellation is a de-escalation, not
        new motion, so it doesn't need approval-gate round-trip latency).
        """
        fields = recommendation_to_proposal(
            behavior_class=msg.behavior_class,
            param_names=list(msg.param_names),
            param_values=list(msg.param_values),
            confidence=float(msg.confidence),
            priority=int(msg.priority),
        )
        if fields is None:
            return
        if "proposal" not in self._pubs:
            return

        proposal = BehaviorProposal()
        proposal.header = Header()
        proposal.header.stamp = self.get_clock().now().to_msg()
        proposal.event_id = msg.recommendation_id or str(uuid.uuid4())[:8]
        proposal.proposed_at = self.get_clock().now().to_msg()
        proposal.source_module = "llm" if msg.trigger_type == "llm" else "rule_engine"
        proposal.person_id = ""
        proposal.tracking_id = -1
        proposal.proposal_type = fields.proposal_type
        proposal.proposal_content = fields.proposal_content
        proposal.urgency = fields.urgency
        proposal.justification = fields.justification
        proposal.nav_goal_pose.position.x = fields.nav_goal_x
        proposal.nav_goal_pose.position.y = fields.nav_goal_y
        proposal.nav_goal_pose.orientation.z = math.sin(fields.nav_goal_yaw * 0.5)
        proposal.nav_goal_pose.orientation.w = math.cos(fields.nav_goal_yaw * 0.5)
        proposal.nav_goal_label = fields.nav_goal_label
        proposal.safety_check_required = fields.safety_check_required
        proposal.raw_llm_command = msg.behavior_class

        self._pubs["proposal"].publish(proposal)

    # ── Multi-person state callbacks (bonbon_multi_person_tracker / fusion) ──

    def _on_person_track(self, msg: PersonTrack) -> None:
        """Caches the person_track_id -> raw_track_id bridge used to look up
        SpatialEntity.person_category for the child-safety modifier (rule 9)."""
        with self._lock:
            if msg.lifecycle_state == "left_scene":
                self._person_track_raw_ids.pop(msg.person_track_id, None)
            elif msg.raw_track_id:
                self._person_track_raw_ids[msg.person_track_id] = msg.raw_track_id

    def _on_human_state(self, msg: HumanState) -> None:
        """Multi-person-aware decision path. Implements the project brief's
        10 example behaviors. Every candidate is dispatched through the SAME
        safety-gated _dispatch_proposal() path the single-person callbacks
        already use — this never bypasses ProposalEvaluator/SafetyState."""
        with self._lock:
            if msg.lifecycle_state == "left_scene":
                snapshot = dict(self._human_states)
                snapshot[msg.person_track_id] = msg
            else:
                self._human_states[msg.person_track_id] = msg
                snapshot = dict(self._human_states)
            privacy_mode = self._privacy_mode

        self._executor.submit(self._decide_multi_person_behavior, msg, snapshot, privacy_mode)

        if msg.lifecycle_state == "left_scene":
            with self._lock:
                self._human_states.pop(msg.person_track_id, None)

    def _decide_multi_person_behavior(
        self, msg: HumanState, snapshot: dict, privacy_mode: bool
    ) -> None:
        """Runs the rule chain (highest priority first) and dispatches at
        most one candidate for this HumanState update."""
        all_states = list(snapshot.values())

        # Rule 6 — safety gesture from ANYONE nearby, regardless of focus.
        candidate = self._behavior_selector.decide_safety_gesture_response(all_states)

        # Rule 3 — a person's own departure is always worth acting on,
        # regardless of who currently has "focus". select_focus_person()
        # deliberately excludes left_scene people from its `present` list
        # (a departed person can never BE the focus), so gating this on
        # focus_id would make decide_departure_close_session() permanently
        # unreachable -- confirmed by direct testing
        # (test_human_state_integration.py), not a hypothetical.
        if candidate is None and msg.lifecycle_state == "left_scene":
            candidate = self._behavior_selector.decide_departure_close_session(msg)

        if candidate is None:
            focus_id = select_focus_person(all_states)
            if focus_id != msg.person_track_id:
                # This update isn't about the current focus person and isn't
                # a safety gesture or departure — nothing new to decide this
                # cycle.
                return
            candidate = (
                self._behavior_selector.decide_arrival_greeting(msg)
                or self._behavior_selector.decide_known_person_greeting(
                    msg, privacy_allows_name=not privacy_mode
                )
                or self._behavior_selector.decide_confused_question_response(msg)
                or self._behavior_selector.decide_calm_supportive_response(msg)
                or self._behavior_selector.decide_pointing_confirmation(msg)
            )

        if candidate is None:
            return

        is_child = self._is_child(candidate.person_track_id)
        candidate = apply_child_safety_modifier(candidate, is_child_nearby=is_child)

        self._dispatch_multi_person_candidate(candidate)

    def _is_child(self, person_track_id: str) -> bool:
        with self._lock:
            raw_id = self._person_track_raw_ids.get(person_track_id, "")
            return self._person_categories.get(raw_id, "unknown") == "child"

    def _dispatch_multi_person_candidate(self, candidate) -> None:
        if candidate.proposal_type == "pause":
            # Safety-gesture pause: always dispatched as a speak (confirmation
            # request) — actual motion pausing is enforced by the Safety
            # Supervisor independently of this proposal.
            self._dispatch_proposal(
                "speak",
                candidate.content,
                candidate.source,
                candidate.person_track_id,
                -1,
                candidate.urgency,
                tts_emotion=candidate.tts_emotion,
            )
            return
        self._dispatch_proposal(
            candidate.proposal_type,
            candidate.content,
            candidate.source,
            candidate.person_track_id,
            -1,
            candidate.urgency,
            tts_emotion=candidate.tts_emotion,
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
        """Send greeting gesture + TTS. This callback only fires on the
        `not was_present` transition in `_on_spatial_entity` -- i.e. every
        call here is genuinely a first contact for this session, so the
        orientation text (not just "hello") is always appropriate, unlike
        `multi_person_behavior_selector.decide_arrival_greeting` which
        distinguishes known vs first-time visitors."""
        if self._actuation_enabled:
            self._dispatch_actuation_gesture("greeting_pose", person_id, tracking_id, priority=5)
        if self._tts_enabled:
            self._dispatch_tts(
                "Hello! I'm BonBon, the hospital's assistant robot. "
                "I can help you find a department, check your appointment or "
                "token, or answer questions about the hospital. "
                "How can I help you today?",
                "warm",
                person_id,
                tracking_id,
            )
        # Transition to INTERACTING after greeting
        time.sleep(2.0)
        self._fsm.transition(BehaviorState.INTERACTING, "greeting completed")

    def _dispatch_emotion_response(self, emotion_msg: HumanEmotionState) -> None:
        """Send gesture and TTS response to detected emotion."""
        dominant = getattr(emotion_msg, "dominant_emotion", "neutral")
        conf = getattr(emotion_msg, "emotion_confidence", 0.5)
        pid = getattr(emotion_msg, "person_id", "")
        tid = getattr(emotion_msg, "tracking_id", -1)

        plan = self._emotion_planner.plan(
            dominant_emotion=dominant,
            emotion_confidence=conf,
            operating_mode=self._operating_mode,
        )

        if plan.gesture_name and self._actuation_enabled:
            self._dispatch_actuation_gesture(plan.gesture_name, pid, tid, priority=7)

        if plan.acknowledgment_text and self._tts_enabled:
            self._dispatch_tts(plan.acknowledgment_text, plan.tts_emotion, pid, tid)

    def _dispatch_emergency_response(self, person_id: str, tracking_id: int) -> None:
        """Handle emergency keyword detection."""
        self.get_logger().error(f"Emergency keyword detected from person '{person_id}'!")
        self._fsm.force_transition(BehaviorState.ALERTING, "emergency keyword detected")

        if self._actuation_enabled:
            self._dispatch_actuation_gesture(
                "emergency_attention_pose", person_id, tracking_id, priority=20
            )
        if self._tts_enabled:
            self._dispatch_tts(
                "Emergency detected! I'm alerting staff immediately.",
                "urgent",
                person_id,
                tracking_id,
            )
        # Publish alert decision + escalate to the operator console.
        self._publish_decision(
            event_id=str(uuid.uuid4())[:8],
            person_id=person_id,
            decision="approved",
            action="alert_operator",
            content="Emergency keyword detected — staff alerted",
            confidence=1.0,
            operator_alerted=True,
        )
        self._raise_operator_alert(
            alert_type="medical_emergency",
            severity=4,  # CRITICAL
            subject_id=person_id or "scene",
            description="Emergency keyword detected in speech",
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
        tts_emotion: str = "neutral",
    ) -> None:
        """Evaluate a proposal and dispatch if approved.

        tts_emotion defaults to "neutral" for existing callers that don't
        carry per-rule emotional context (LLM/legacy proposals). Callers
        that DO know the right tone (the multi-person rule chain's
        BehaviorCandidate.tts_emotion, the single-person
        EmotionAwareResponsePlanner path's plan.tts_emotion) pass it
        explicitly -- this was previously silently dropped for the
        multi-person path only (docs/HUMAN_STATE_FUSION.md /
        bonbon_behavior_engine.core.multi_person_behavior_selector
        computed a real per-rule tts_emotion on every BehaviorCandidate
        that never reached _dispatch_tts).
        """
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
            if self._safety_check_blocks(person_id, "text_response", result.approved_content):
                return
            self._dispatch_tts(result.approved_content, tts_emotion, person_id, tracking_id)
        elif result.approved_action == "gesture" and self._actuation_enabled:
            if self._safety_check_blocks(person_id, "actuation_request", result.approved_content):
                return
            self._dispatch_actuation_gesture(
                result.approved_content, person_id, tracking_id, priority=5
            )

    def _safety_check_blocks(self, person_id: str, action_type: str, content: str) -> bool:
        """Finding 8 fix: independent SafetySeparationGuard check, on top
        of ProposalEvaluator's own (LLM-source-only) risk classification.
        Returns True if the shared safety-separation authority says this
        specific action must not be dispatched -- content-risk categories
        (medical-diagnosis-sounding text, leaked privacy fields) mainly,
        since actuation_request/text_response are never in the guard's
        direct-hardware-control blocklist on their own."""
        if self._safety_guard is None:
            return False
        try:
            classified = self._safety_guard.classify(
                "behavior_engine", action_type, {"text": content, "person_id": person_id}
            )
        except Exception as exc:  # noqa: BLE001 -- a guard failure must never crash dispatch
            self.get_logger().debug(f"safety_separation_guard check error (non-fatal): {exc}")
            return False
        if classified.blocked:
            self.get_logger().warning(
                f"Dispatch blocked by safety_separation_guard: {classified.category.value} — {classified.reason}"
            )
        return classified.blocked

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
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id = str(uuid.uuid4())[:8]
        msg.requested_at = self.get_clock().now().to_msg()
        msg.source_module = "bonbon_behavior_engine"
        msg.person_id = person_id
        msg.tracking_id = tracking_id
        msg.gesture_name = gesture_name
        msg.priority = priority
        msg.speed_scale = speed_scale
        msg.interruptible = priority < 15
        msg.timeout_sec = 10.0
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
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.text = text
        msg.emotion = emotion
        msg.person_id = person_id
        msg.tracking_id = tracking_id
        msg.priority = 5
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
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id = event_id
        msg.decided_at = self.get_clock().now().to_msg()
        msg.source_module = "bonbon_behavior_engine"
        msg.person_id = person_id
        msg.decision = decision
        msg.approved_action = action
        msg.approved_content = content
        msg.safety_approved = True
        msg.confidence = float(confidence)
        msg.operator_alerted = operator_alerted
        msg.logged = True
        self._pubs["decision"].publish(msg)

    # ── Service handlers ───────────────────────────────────────────────────────

    def _handle_evaluate_command(
        self,
        request: EvaluateCommand.Request,
        response: EvaluateCommand.Response,
    ) -> EvaluateCommand.Response:
        """Evaluate a command from an operator, speech, or LLM source."""
        risk = self._clf.classify(request.command_text, source=request.source)
        response.safe = risk.is_safe
        response.risk_level = risk.risk_level
        response.reasons = risk.reasons
        response.recommended_action = risk.recommended_action
        response.modified_command = ""

        if not risk.is_safe:
            self.get_logger().warn(
                f"EvaluateCommand: CRITICAL risk from '{request.source}': "
                f"'{request.command_text[:60]}…'"
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
            response.success = False
            response.previous_mode = prev
            response.error_message = f"Unknown mode '{request.mode}'."
            return response

        with self._lock:
            self._operating_mode = request.mode
        self._evaluator.set_operating_mode(request.mode)

        self.get_logger().info(
            f"Operating mode changed: '{prev}' → '{request.mode}' by operator '{request.operator_id}'."
        )
        response.success = True
        response.previous_mode = prev
        response.error_message = ""
        return response

    def _handle_health_check(
        self,
        request: HealthCheck.Request,
        response: HealthCheck.Response,
    ) -> HealthCheck.Response:
        gate_stats = self._llm_gate.stats()
        response.healthy = True
        response.status = (
            f"active; state={self._fsm.current_state_name}; "
            f"mode={self._operating_mode}; "
            f"safety={self._safety_level_name}; "
            f"llm_gate: {gate_stats['approved']}/{gate_stats['total']} approved"
        )
        response.warnings = []
        response.errors = []
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
