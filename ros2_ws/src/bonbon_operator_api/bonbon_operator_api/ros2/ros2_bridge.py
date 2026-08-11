"""ROS2DashboardBridge — optional ROS2 integration layer.

Design
------
* rclpy is imported conditionally so the API server can run without a live
  ROS2 environment (useful for unit tests and CI).
* The ROS2 executor runs in a dedicated background daemon thread.
* All communication back to the FastAPI layer uses asyncio queues — the
  bridge puts events onto the queue; the WebSocket router gets them out.
* Service calls use a single-shot future pattern with configurable timeout.

Safety contract
---------------
This bridge NEVER bypasses the Safety Supervisor. It publishes commands only
after the SafetyCommandGate has approved them. The bridge does not implement
its own safety logic — it only relays already-approved messages.

Topics and services below were corrected during a final verification pass:
the bridge originally subscribed to topic names/types that did not match any
real BonBon publisher (verified by grep against every node in the
workspace), and every command dispatch method was a hardcoded stub that
always reported success without calling anything. Real targets that
verifiably exist are now wired for real (navigate, cancel_task, dock,
speak); commands with no real backing service anywhere in the codebase
(emergency_stop — e-stop is hardware/GPIO-only with no software trigger
today, pause, resume, restart_module, get_config, set_config, memory_query,
rag_query) now honestly report unavailable rather than silently lying about
success — see `_NOT_IMPLEMENTED` below.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from bonbon_operator_api.ros2.distributed_status_tracker import DistributedStatusTracker
from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator

logger = logging.getLogger(__name__)

# Try to import rclpy; fall back gracefully when not available
try:
    import rclpy
    from bonbon_msgs.msg import (
        ActuationStatus,
        BehaviorDecision,
        BehaviorProposal,
        ComponentFaultArray,
        DegradedModeStatus,
        HumanEmotionState,
        LLMResponse,
        ModuleHealth,
        NavigationStatus,
        PerceptionEfficiencyMetrics,
        PersonTrack,
        ResourceUsage,
        SafetyState,
        SpeechTranscription,
        TTSRequest,
    )
    from bonbon_srvs.srv import CancelNavigation, GetNearestCharger, NavigateTo
    from geometry_msgs.msg import PoseStamped
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import BatteryState
    from std_msgs.msg import String

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — ROS2 bridge running in stub mode")

# Topic names — verified against the actual publisher in each owning
# package, not guessed. See module docstring.
_TOPIC_SAFETY_STATE = "/bonbon/safety/state"  # bonbon_safety/safety_supervisor_node, SafetyState
_TOPIC_BATTERY = "/bonbon/battery/state"  # bonbon_hal/battery_node, sensor_msgs/BatteryState
_TOPIC_NAV_STATUS = "/navigation/status"  # bonbon_navigation/navigation_node, NavigationStatus
_TOPIC_TTS_HEALTH = "/bonbon/tts/health"  # bonbon_tts/tts_node, std_msgs/String (JSON)
_TOPIC_ACTUATION_STATUS = "/bonbon/actuation/status"  # bonbon_actuation, ActuationStatus
_TOPIC_PERSON_TRACKS = "/bonbon/persons/tracks"  # bonbon_multi_person_tracker, PersonTrack
_TOPIC_RESOURCE_USAGE = "/bonbon/system/resource_usage"  # bonbon_safety, ResourceUsage
_TOPIC_PERCEPTION_METRICS = "/bonbon/perception_efficiency/metrics"  # bonbon_perception_efficiency
_TOPIC_FAULT_REGISTRY = (
    "/bonbon/fault_manager/registry"  # bonbon_fault_manager, ComponentFaultArray
)
_TOPIC_SPEECH_TRANSCRIPTION = "/speech/transcription"  # bonbon_speech/speech_node
_TOPIC_LLM_RESPONSE = "/llm/response"  # bonbon_llm/llm_orchestrator_node
_TOPIC_HUMAN_EMOTION_STATE = (
    "/bonbon/affective/human_state"  # bonbon_human_state_fusion/human_state_fusion_node
)

# bonbon_msgs/ComponentFault.msg's uint8 fault_level constants -> name,
# for the dashboard-facing string field (ComponentFaultData.fault_level).
_FAULT_LEVEL_NAMES = ["OK", "WARNING", "DEGRADED", "FAULT", "CRITICAL", "BLOCKED"]

# bonbon_msgs/LLMResponse.msg's uint8 status constants -> name.
_LLM_STATUS_NAMES = [
    "ok",
    "low_conf",
    "safety_block",
    "hallucination",
    "llm_error",
    "fallback",
]


def _fault_level_name(level: int) -> str:
    if 0 <= level < len(_FAULT_LEVEL_NAMES):
        return _FAULT_LEVEL_NAMES[level]
    return "UNKNOWN"


def _llm_status_name(status: int) -> str:
    if 0 <= status < len(_LLM_STATUS_NAMES):
        return _LLM_STATUS_NAMES[status]
    return "unknown"


# Three-Pi distributed topics — see config/distributed/topic_contracts.yaml
# and docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md. Pi-1 only ever READS
# safety/approval, safety/rejection, degraded_mode, and pi2/pi3 heartbeats
# (never publishes anything actuation-relevant); it WRITES operator
# proposals only, never a direct command.
_TOPIC_SAFETY_APPROVAL = (
    "/bonbon/safety/approval"  # bonbon_motion_approval_gateway, BehaviorDecision
)
_TOPIC_SAFETY_REJECTION = (
    "/bonbon/safety/rejection"  # bonbon_motion_approval_gateway, BehaviorDecision
)
_TOPIC_DEGRADED_MODE = (
    "/bonbon/system/degraded_mode"  # bonbon_authority_manager, DegradedModeStatus
)
_TOPIC_PI2_HEARTBEAT = "/bonbon/pi2/heartbeat"  # bonbon_distributed_safety, ModuleHealth
_TOPIC_PI3_HEARTBEAT = "/bonbon/pi3/heartbeat"  # bonbon_distributed_safety, ModuleHealth
_TOPIC_OPERATOR_PROPOSAL = (
    "/bonbon/operator/proposal"  # THIS bridge publishes, bonbon_msgs/BehaviorProposal
)
# edge_ai_runtime_node (Pi-2, bonbon_edge_ai_runtime) -- 6 JSON-over-String
# status topics, Edge AI Runtime brief Phase 12. Same "String + json.loads"
# pattern already used for _TOPIC_TTS_HEALTH above -- these carry
# STATEFUL data (accumulated safety-block counts, cache hit rates, live
# resource readings) that only the real, persistent Pi-2 process has;
# see docs/EDGE_AI_DASHBOARD_REPORT.md for why the REST endpoints read
# this cache rather than constructing a fresh (and therefore always-empty)
# EdgeAIDashboardPublisher per request.
_TOPIC_EDGE_AI_STATUS = "/bonbon/edge_ai/status"
_TOPIC_EDGE_AI_MODELS = "/bonbon/edge_ai/models"
_TOPIC_EDGE_AI_ROUTES = "/bonbon/edge_ai/routes"
_TOPIC_EDGE_AI_RESOURCES = "/bonbon/edge_ai/resources"
_TOPIC_EDGE_AI_SAFETY = "/bonbon/edge_ai/safety"
_TOPIC_EDGE_AI_CACHE = "/bonbon/edge_ai/cache"

# Curated set of ModuleHealth topics surfaced as dashboard module cards.
# There is no single aggregate "/bonbon/modules/status" topic anywhere in
# the codebase (verified) — every node publishes its own health
# independently. Subscribing to literally all of them would mean keeping
# this list in lockstep with every package; this curated set covers the
# subsystems an operator actually needs at a glance.
_MODULE_HEALTH_TOPICS = {
    "safety_supervisor": "/bonbon/safety/safety_supervisor_node/health",
    "navigation": "/health/navigation",
    "actuation": "/bonbon/actuation/actuation_node/health",
    "vision": "/bonbon/vision/vision_node/health",
    "speech": "/health/speech",
    # "tts" deliberately excluded: /bonbon/tts/health carries std_msgs/String
    # (JSON), not bonbon_msgs/ModuleHealth like every other entry here --
    # tts_node has no separate ModuleHealth publisher anywhere. Confirmed on
    # real Pi-2 hardware: subscribing here with the wrong type against an
    # already-live String publisher on the exact same topic name throws
    # "invalid allocator" from rcl_subscription and aborts THIS NODE'S
    # __init__ entirely -- every other subscription below it silently never
    # got created either, so the whole bridge reported "start failed" with
    # no topic data at all, not just TTS. TTS health is already covered
    # correctly via _TOPIC_TTS_HEALTH/_on_tts below.
    "llm": "/health/llm",
    "perception_efficiency": "/bonbon/perception_efficiency/perception_efficiency_node/health",
}

# Service names — only created for commands with a confirmed real target.
_SVC_NAVIGATE = "/navigation/navigate_to"
_SVC_CANCEL_NAVIGATION = "/navigation/cancel"
_SVC_GET_NEAREST_CHARGER = "/navigation/get_nearest_charger"
_TOPIC_TTS_REQUEST = "/bonbon/tts/request"

_SERVICE_TIMEOUT_SEC = 5.0
# NavigateTo blocks server-side until arrival or failure (default 120s) —
# the future-wait timeout for this one call must exceed that, or the bridge
# gives up on a goal that is still actually running.
_NAVIGATE_SERVICE_TIMEOUT_SEC = 130.0

# Commands with no real backing service/topic anywhere in the codebase
# (verified by grep — not a guess). Honestly report unavailable instead of
# the previous hardcoded "success": True, which actively lied to an
# operator about whether e.g. emergency_stop did anything.
_NOT_IMPLEMENTED = {
    "emergency_stop": (
        "No software e-stop trigger exists in this codebase — emergency stop "
        "is hardware/GPIO-only (see bonbon_safety/estop_node). Use the "
        "physical e-stop."
    ),
    "pause": "No pause service exists yet — only navigate/cancel are implemented.",
    "resume": "No resume service exists yet — only navigate/cancel are implemented.",
    "restart_module": (
        "Generic module restart is not implemented — ROS2 lifecycle "
        "transitions for an arbitrary node require state-aware sequencing "
        "this bridge does not yet provide."
    ),
    "get_config": "No config service exists in this codebase yet.",
    "set_config": "No config service exists in this codebase yet.",
    "memory_query": "No memory query service exists in this codebase yet.",
    "rag_query": (
        "LLMQuery.srv is defined for this purpose but bonbon_llm's "
        "llm_orchestrator_node does not yet create a server for it."
    ),
}


class BridgeError(Exception):
    """Raised when a ROS2 service call fails or times out."""

    def __init__(self, message: str, code: str = "BRIDGE_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ROS2DashboardBridge:
    """Connect the FastAPI dashboard to ROS2 topics and services.

    Parameters
    ----------
    aggregator:
        ``RobotStatusAggregator`` that receives topic callback data.
    event_queue:
        ``asyncio.Queue`` for broadcasting events to WebSocket clients.
        Should be set before calling ``start()``.
    node_name:
        Name of the ROS2 node created by this bridge.
    """

    def __init__(
        self,
        aggregator: RobotStatusAggregator,
        event_queue: asyncio.Queue | None = None,
        node_name: str = "bonbon_dashboard_bridge",
    ) -> None:
        self._aggregator = aggregator
        self._event_queue: asyncio.Queue | None = event_queue
        self._node_name = node_name
        self._loop: asyncio.AbstractEventLoop | None = None

        self._node = None
        self._executor = None
        self._spin_thread: threading.Thread | None = None
        self._running = False
        # Populated even when the bridge isn't ready, so REST/WS callers
        # always get a real (if empty) snapshot rather than a KeyError.
        self._offline_distributed_tracker = DistributedStatusTracker()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_event_queue(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        self._event_queue = queue
        self._loop = loop

    def start(self) -> None:
        """Start the ROS2 executor in a background daemon thread."""
        if not _ROS2_AVAILABLE:
            logger.warning("ROS2 not available — bridge not started")
            return
        if self._running:
            return
        try:
            if not rclpy.ok():
                rclpy.init()
            self._node = _DashboardNode(
                self._node_name,
                self._aggregator,
                self._emit_event,
            )
            self._executor = MultiThreadedExecutor(num_threads=2)
            self._executor.add_node(self._node)
            self._spin_thread = threading.Thread(
                target=self._spin_loop,
                daemon=True,
                name="ros2-bridge-spin",
            )
            self._running = True
            self._spin_thread.start()
            logger.info("ROS2 bridge started (node=%s)", self._node_name)
        except Exception as exc:
            logger.error("ROS2 bridge start failed: %s", exc)
            self._running = False

    def stop(self) -> None:
        """Shutdown the ROS2 executor and background thread."""
        self._running = False
        if self._executor:
            try:
                self._executor.shutdown(timeout_sec=2.0)
            except Exception:
                pass
        if self._node:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=3.0)
        logger.info("ROS2 bridge stopped")

    def _spin_loop(self) -> None:
        try:
            self._executor.spin()
        except Exception as exc:
            if self._running:
                logger.error("ROS2 bridge spin error: %s", exc)

    # ------------------------------------------------------------------
    # Service call wrappers (called from FastAPI async context)
    # These block a thread pool worker — that is acceptable for commands.
    # ------------------------------------------------------------------

    def call_emergency_stop(self, reason: str) -> dict[str, Any]:
        return self._not_implemented("emergency_stop")

    def call_speak(self, text: str, language: str, priority: str) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.publish_speak(text, language, priority)

    def call_navigate(
        self,
        goal_x: float,
        goal_y: float,
        goal_yaw: float | None,
        map_id: str | None,
        speed_limit_mps: float | None,
    ) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_navigate(
            goal_x, goal_y, goal_yaw, timeout_sec=_NAVIGATE_SERVICE_TIMEOUT_SEC
        )

    def call_pause(self) -> dict[str, Any]:
        return self._not_implemented("pause")

    def call_resume(self) -> dict[str, Any]:
        return self._not_implemented("resume")

    def call_dock(self, station_id: str | None) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_dock(station_id, timeout_sec=_NAVIGATE_SERVICE_TIMEOUT_SEC)

    def call_cancel_task(self, task_id: str | None) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_cancel(task_id)

    def call_restart_module(self, module_name: str) -> dict[str, Any]:
        return self._not_implemented("restart_module")

    def call_get_config(self, key: str) -> dict[str, Any]:
        return self._not_implemented("get_config")

    def call_set_config(self, key: str, value: Any) -> dict[str, Any]:
        return self._not_implemented("set_config")

    def call_memory_query(self, query: str, limit: int) -> dict[str, Any]:
        return self._not_implemented("memory_query")

    def call_rag_query(self, query: str, collection: str, top_k: int) -> dict[str, Any]:
        return self._not_implemented("rag_query")

    def call_operator_proposal(
        self,
        proposal_type: str,
        proposal_content: str,
        urgency: float,
        justification: str,
        person_id: str = "",
    ) -> dict[str, Any]:
        """Publish an operator-sourced BehaviorProposal to Pi-3's
        motion_approval_gateway. This is NOT a command — it is a proposal
        that Pi-3's safety supervisor may approve, reject, or escalate,
        exactly like any LLM/gesture/rule-engine proposal from Pi-2 (see
        docs/INTER_PI_COMMUNICATION_POLICY.md Rule 10: no source gets a
        bypass). Publishing succeeding only means the proposal was sent,
        NOT that it will be approved.
        """
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.publish_operator_proposal(
            proposal_type, proposal_content, urgency, justification, person_id
        )

    def get_distributed_snapshot(self) -> dict[str, Any]:
        """Pi-1's live view of Pi-2/Pi-3 liveness + the most recent motion
        approval/rejection/degraded-mode state. Honest even when the
        bridge isn't running: every Pi reports LOST, never a stale-but-
        plausible-looking cached value."""
        tracker = self._node._distributed if self._ready() else self._offline_distributed_tracker
        return {"bridge_ready": self._ready(), **tracker.snapshot()}

    def get_edge_ai_snapshot(self, channel: str) -> dict[str, Any] | None:
        """Latest JSON status edge_ai_runtime_node (Pi-2) published on
        /bonbon/edge_ai/<channel>, or None if no message has been
        received yet -- never fabricates a zero/empty snapshot just
        because the bridge happens to be running (rule 11: dashboard
        must show real status, not a fake green default)."""
        if not self._ready():
            return None
        return self._node._edge_ai_status.get(channel)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ready(self) -> bool:
        return _ROS2_AVAILABLE and self._running and self._node is not None

    def _not_implemented(self, name: str) -> dict[str, Any]:
        logger.warning("Command '%s' has no real backing service — rejecting honestly", name)
        return {
            "success": False,
            "error": "NOT_IMPLEMENTED",
            "message": _NOT_IMPLEMENTED.get(name, "Not implemented."),
            "service": name,
        }

    def _emit_event(self, channel: str, event: str, data: dict[str, Any]) -> None:
        """Push an event onto the asyncio queue (called from ROS2 thread)."""
        if self._event_queue is None or self._loop is None:
            return
        try:
            msg = {"channel": channel, "event": event, "data": data, "timestamp": time.time()}
            asyncio.run_coroutine_threadsafe(self._event_queue.put(msg), self._loop)
        except Exception as exc:
            logger.debug("Event emit error: %s", exc)


# ---------------------------------------------------------------------------
# Internal ROS2 node (only instantiated when rclpy is available)
# ---------------------------------------------------------------------------

if _ROS2_AVAILABLE:
    import json as _json

    _HEALTH_TO_LABEL = {
        ModuleHealth.OK: "healthy",
        ModuleHealth.WARN: "degraded",
        ModuleHealth.ERROR: "critical",
        ModuleHealth.STALE: "critical",
    }

    class _DashboardNode(Node):
        """Internal ROS2 node that subscribes to all relevant topics."""

        def __init__(
            self,
            name: str,
            aggregator: RobotStatusAggregator,
            emit_cb: Callable,
        ) -> None:
            super().__init__(name)
            self._agg = aggregator
            self._emit = emit_cb
            self._person_track_ids: set[str] = set()
            self._distributed = DistributedStatusTracker()
            # channel name ("status"|"models"|"routes"|"resources"|"safety"|"cache")
            # -> latest parsed JSON dict from edge_ai_runtime_node, or
            # absent if no message has been received yet -- never
            # defaulted to an empty dict here, so callers can honestly
            # distinguish "not received yet" from "received, empty".
            self._edge_ai_status: dict[str, dict] = {}

            _best_effort = QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )
            _reliable_transient = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )

            # Subscriptions — real topics/types, verified against each
            # owning package's actual publisher.
            self.create_subscription(
                SafetyState, _TOPIC_SAFETY_STATE, self._on_safety, _reliable_transient
            )
            self.create_subscription(BatteryState, _TOPIC_BATTERY, self._on_battery, _best_effort)
            self.create_subscription(
                NavigationStatus, _TOPIC_NAV_STATUS, self._on_navigation, _best_effort
            )
            self.create_subscription(String, _TOPIC_TTS_HEALTH, self._on_tts, _best_effort)
            self.create_subscription(
                ActuationStatus, _TOPIC_ACTUATION_STATUS, self._on_actuation, _best_effort
            )
            self.create_subscription(
                PersonTrack, _TOPIC_PERSON_TRACKS, self._on_person_track, _best_effort
            )
            self.create_subscription(
                ResourceUsage, _TOPIC_RESOURCE_USAGE, self._on_resource_usage, _best_effort
            )
            self.create_subscription(
                PerceptionEfficiencyMetrics,
                _TOPIC_PERCEPTION_METRICS,
                self._on_perception_metrics,
                _best_effort,
            )
            self.create_subscription(
                ComponentFaultArray,
                _TOPIC_FAULT_REGISTRY,
                self._on_component_faults,
                _reliable_transient,
            )
            # Live conversation feed -- what the robot itself just heard,
            # said, and inferred, as distinct from the dashboard's own
            # operator-testbench fields (browser mic/one-shot LLM calls).
            self.create_subscription(
                SpeechTranscription,
                _TOPIC_SPEECH_TRANSCRIPTION,
                self._on_transcript,
                _best_effort,
            )
            self.create_subscription(
                LLMResponse, _TOPIC_LLM_RESPONSE, self._on_llm_response, _best_effort
            )
            self.create_subscription(
                HumanEmotionState,
                _TOPIC_HUMAN_EMOTION_STATE,
                self._on_emotion_state,
                _best_effort,
            )
            for module_key, topic in _MODULE_HEALTH_TOPICS.items():
                self.create_subscription(
                    ModuleHealth,
                    topic,
                    lambda msg, key=module_key: self._on_module_health(key, msg),
                    _best_effort,
                )

            # Three-Pi distributed subscriptions — read-only, see
            # docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md. Pi-1 never
            # subscribes to /bonbon/behavior/proposal or /bonbon/motion/
            # approved_command's raw command content, only the approval/
            # rejection/degraded-mode OUTCOME and peer liveness.
            self.create_subscription(
                BehaviorDecision,
                _TOPIC_SAFETY_APPROVAL,
                self._on_safety_approval,
                _reliable_transient,
            )
            self.create_subscription(
                BehaviorDecision,
                _TOPIC_SAFETY_REJECTION,
                self._on_safety_rejection,
                _reliable_transient,
            )
            self.create_subscription(
                DegradedModeStatus,
                _TOPIC_DEGRADED_MODE,
                self._on_degraded_mode,
                _reliable_transient,
            )
            self.create_subscription(
                ModuleHealth,
                _TOPIC_PI2_HEARTBEAT,
                lambda msg: self._distributed.record_heartbeat("pi2"),
                _best_effort,
            )
            self.create_subscription(
                ModuleHealth,
                _TOPIC_PI3_HEARTBEAT,
                lambda msg: self._distributed.record_heartbeat("pi3"),
                _best_effort,
            )

            # edge_ai_runtime_node status (Edge AI Runtime brief Phase 12)
            for _channel, _topic in (
                ("status", _TOPIC_EDGE_AI_STATUS),
                ("models", _TOPIC_EDGE_AI_MODELS),
                ("routes", _TOPIC_EDGE_AI_ROUTES),
                ("resources", _TOPIC_EDGE_AI_RESOURCES),
                ("safety", _TOPIC_EDGE_AI_SAFETY),
                ("cache", _TOPIC_EDGE_AI_CACHE),
            ):
                self.create_subscription(
                    String,
                    _topic,
                    lambda msg, ch=_channel: self._on_edge_ai_status(ch, msg),
                    _best_effort,
                )

            # Service clients — only for commands with a confirmed real target.
            self._cli_navigate = self.create_client(NavigateTo, _SVC_NAVIGATE)
            self._cli_cancel = self.create_client(CancelNavigation, _SVC_CANCEL_NAVIGATION)
            self._cli_get_charger = self.create_client(GetNearestCharger, _SVC_GET_NEAREST_CHARGER)
            self._pub_tts_request = self.create_publisher(
                TTSRequest, _TOPIC_TTS_REQUEST, _best_effort
            )
            self._pub_operator_proposal = self.create_publisher(
                BehaviorProposal, _TOPIC_OPERATOR_PROPOSAL, _best_effort
            )

        # -- Subscription callbacks --

        def _on_safety(self, msg: SafetyState) -> None:
            data = {
                "state": (msg.state_name or "unknown").lower(),
                "active_faults": list(msg.degraded_modules),
                "last_event_ts": None,
                "watchdog_ok": not msg.requires_manual_reset,
            }
            self._agg.update_safety(data)
            self._emit("safety-events", "safety_state_changed", data)

        def _on_component_faults(self, msg: ComponentFaultArray) -> None:
            faults = [
                {
                    "component_id": c.component_id,
                    "subsystem": c.subsystem,
                    "affected_pi": c.affected_pi,
                    "fault_level": _fault_level_name(c.fault_level),
                    "error_code": c.error_code,
                    "message": c.message,
                    "recovery_action": c.recovery_action,
                    "dashboard_visible": c.dashboard_visible,
                    "occurrence_count": c.occurrence_count,
                }
                for c in msg.components
            ]
            self._agg.update_component_faults(faults, _fault_level_name(msg.worst_level))
            self._emit(
                "component-health",
                "component_faults_changed",
                {
                    "component_faults": faults,
                    "worst_fault_level": _fault_level_name(msg.worst_level),
                },
            )

        def _on_transcript(self, msg: SpeechTranscription) -> None:
            data = {
                "transcript_text": msg.text,
                "transcript_confidence": msg.confidence,
                "transcript_speaker_id": msg.speaker_id,
                "transcript_ts": time.time(),
            }
            self._agg.update_transcript(data)
            self._emit("robot-status", "transcript_updated", data)

        def _on_llm_response(self, msg: LLMResponse) -> None:
            data = {
                "llm_response_text": msg.text,
                "llm_status": _llm_status_name(msg.status),
                "llm_confidence": msg.confidence,
                "llm_model_name": msg.model_name,
                "llm_ts": time.time(),
            }
            self._agg.update_llm_response(data)
            self._emit("robot-status", "llm_response_updated", data)

        def _on_emotion_state(self, msg: HumanEmotionState) -> None:
            data = {
                "emotion_dominant": msg.dominant_state,
                "emotion_confidence": msg.dominant_confidence,
                "emotion_recommended_style": msg.recommended_response_style,
                "emotion_requires_operator_alert": msg.requires_operator_alert,
                "emotion_ts": time.time(),
            }
            self._agg.update_emotion(data)
            self._emit("robot-status", "emotion_state_updated", data)

        def _on_battery(self, msg: BatteryState) -> None:
            # sensor_msgs/BatteryState.percentage is a 0.0-1.0 fraction (or
            # NaN if unknown); BatteryData.percentage is 0-100.
            pct = msg.percentage
            pct = 0.0 if pct != pct else max(0.0, min(1.0, pct)) * 100.0  # NaN-safe
            data = {
                "voltage_v": msg.voltage,
                "percentage": pct,
                "is_charging": msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING,
                "estimated_runtime_min": None,
            }
            self._agg.update_battery(data)

        def _on_navigation(self, msg: NavigationStatus) -> None:
            _STATE_LABELS = {
                NavigationStatus.STATE_IDLE: "idle",
                NavigationStatus.STATE_PLANNING: "navigating",
                NavigationStatus.STATE_EXECUTING: "navigating",
                NavigationStatus.STATE_RECOVERING: "navigating",
                NavigationStatus.STATE_DOCKING: "navigating",
                NavigationStatus.STATE_ARRIVED: "succeeded",
                NavigationStatus.STATE_BLOCKED: "paused",
                NavigationStatus.STATE_FAILED: "failed",
                NavigationStatus.STATE_CANCELLED: "idle",
                NavigationStatus.STATE_SAFETY_STOPPED: "paused",
            }
            data = {
                "state": _STATE_LABELS.get(msg.state, "idle"),
                "current_x": msg.current_pose.pose.position.x,
                "current_y": msg.current_pose.pose.position.y,
                "current_yaw": 0.0,
                "goal_x": None,
                "goal_y": None,
                "progress_pct": msg.progress_pct if msg.active_goal_id else None,
                "active_map": None,
            }
            self._agg.update_navigation(data)
            self._emit("navigation-events", "navigation_state_changed", data)
            self._agg.update_active_task(msg.active_goal_id or None)

        def _on_tts(self, msg: String) -> None:
            try:
                payload = _json.loads(msg.data)
            except Exception:
                payload = {}
            data = {
                "is_speaking": payload.get("status") == "speaking",
                "current_text": payload.get("current_text"),
                "queue_depth": payload.get("queue_depth", 0),
            }
            self._agg.update_tts(data)

        def _on_edge_ai_status(self, channel: str, msg: String) -> None:
            try:
                payload = _json.loads(msg.data)
            except (ValueError, TypeError) as exc:
                self.get_logger().warning(f"edge_ai/{channel}: failed to parse JSON: {exc}")
                return
            self._edge_ai_status[channel] = payload

        def _on_actuation(self, msg: ActuationStatus) -> None:
            data = {
                "linear_velocity_mps": 0.0,
                "angular_velocity_rps": 0.0,
                "motors_enabled": msg.status in ("queued", "executing") and not msg.safety_blocked,
            }
            self._agg.update_actuation(data)

        def _on_person_track(self, msg: PersonTrack) -> None:
            if msg.lifecycle_state == "left_scene":
                self._person_track_ids.discard(msg.person_track_id)
            else:
                self._person_track_ids.add(msg.person_track_id)
            self._agg.update_perception(
                {
                    "camera_active": True,  # we are receiving PersonTrack updates at all
                    "lidar_active": None,
                    "persons_detected": len(self._person_track_ids),
                    "obstacle_distance_m": None,
                }
            )

        def _on_resource_usage(self, msg: ResourceUsage) -> None:
            self._agg.update_performance(
                {
                    "cpu_percent": msg.cpu_percent,
                    "memory_percent": msg.memory_percent,
                    "disk_free_percent": msg.disk_free_percent,
                    "resource_data_available": msg.available,
                    "recommended_load_shed": msg.recommended_load_shed,
                }
            )

        def _on_perception_metrics(self, msg: PerceptionEfficiencyMetrics) -> None:
            # Richer overlay on top of ResourceUsage -- only present while
            # bonbon_perception_efficiency is running. cpu/memory here
            # mirror ResourceUsage (see that message's own docstring) so
            # update_performance's partial dict merge keeps both consistent
            # whichever arrives most recently.
            self._agg.update_performance(
                {
                    "cpu_percent": msg.cpu_percent,
                    "memory_percent": msg.memory_percent,
                    "recommended_load_shed": msg.recommended_load_shed,
                    "load_level": msg.load_level,
                    "degraded_mode_active": msg.degraded_mode_active,
                    "avg_module_latency_ms": msg.avg_latency_ms,
                    "max_module_latency_ms": msg.max_latency_ms,
                    "total_module_errors": msg.total_errors,
                }
            )

        def _on_module_health(self, module_key: str, msg: ModuleHealth) -> None:
            data = {
                "state": "active" if msg.status == ModuleHealth.OK else "degraded",
                "health": _HEALTH_TO_LABEL.get(msg.status, "unknown"),
                "message": msg.status_text,
            }
            self._agg.update_module(module_key, data)
            self._emit("diagnostics", "module_status_changed", {"module": module_key, **data})

        def _decision_to_dict(self, msg: "BehaviorDecision") -> dict[str, Any]:
            return {
                "event_id": msg.event_id,
                "proposal_event_id": msg.proposal_event_id,
                "decision": msg.decision,
                "approved_action": msg.approved_action,
                "approved_content": msg.approved_content,
                "safety_approved": msg.safety_approved,
                "rejection_reason": msg.rejection_reason,
                "modification_note": msg.modification_note,
                "confidence": msg.confidence,
                "operator_alerted": msg.operator_alerted,
            }

        def _on_safety_approval(self, msg: BehaviorDecision) -> None:
            data = self._decision_to_dict(msg)
            self._distributed.record_approval(data)
            self._emit("safety-approvals", "proposal_approved", data)

        def _on_safety_rejection(self, msg: BehaviorDecision) -> None:
            data = self._decision_to_dict(msg)
            self._distributed.record_rejection(data)
            self._emit("safety-rejections", "proposal_rejected", data)
            if data["operator_alerted"]:
                self._emit("safety-events", "proposal_escalated", data)

        def _on_degraded_mode(self, msg: DegradedModeStatus) -> None:
            data = {
                "is_degraded": msg.is_degraded,
                "reason": msg.reason,
                "duration_sec": msg.duration_sec,
            }
            self._distributed.record_degraded_mode(data)
            self._emit("degraded-mode", "degraded_mode_changed", data)

        # -- Command dispatch (real service/topic clients) --

        def publish_operator_proposal(
            self,
            proposal_type: str,
            proposal_content: str,
            urgency: float,
            justification: str,
            person_id: str,
        ) -> dict[str, Any]:
            msg = BehaviorProposal()
            msg.event_id = str(uuid.uuid4())
            msg.source_module = "operator"
            msg.person_id = person_id or ""
            msg.proposal_type = proposal_type
            msg.proposal_content = proposal_content
            msg.urgency = float(urgency)
            msg.justification = justification or ""
            msg.safety_check_required = True
            self._pub_operator_proposal.publish(msg)
            return {
                "success": True,
                "service": "operator_proposal",
                "event_id": msg.event_id,
                "note": "Proposal sent to Pi-3 for safety validation -- not yet approved.",
            }

        def publish_speak(self, text: str, language: str, priority: str) -> dict[str, Any]:
            _PRIORITY_MAP = {"low": 1, "normal": 5, "high": 10}
            msg = TTSRequest()
            msg.text = text
            msg.priority = _PRIORITY_MAP.get((priority or "normal").lower(), 5)
            msg.language = language or ""
            msg.request_id = str(uuid.uuid4())
            msg.speed_factor = 1.0
            self._pub_tts_request.publish(msg)
            return {"success": True, "service": "speak", "request_id": msg.request_id}

        def call_navigate(
            self, goal_x: float, goal_y: float, goal_yaw: float | None, timeout_sec: float
        ) -> dict[str, Any]:
            if not self._cli_navigate.wait_for_service(timeout_sec=2.0):
                return {"success": False, "error": "navigate_to service unavailable"}
            req = NavigateTo.Request()
            req.goal_id = str(uuid.uuid4())
            req.named_location = ""
            req.target_pose = PoseStamped()
            req.target_pose.pose.position.x = goal_x
            req.target_pose.pose.position.y = goal_y
            req.timeout_sec = float(timeout_sec)
            req.enqueue = False
            req.requester_id = "dashboard"
            return self._call_sync(self._cli_navigate, req, timeout_sec)

        def call_cancel(self, task_id: str | None) -> dict[str, Any]:
            if not self._cli_cancel.wait_for_service(timeout_sec=2.0):
                return {"success": False, "error": "cancel service unavailable"}
            req = CancelNavigation.Request()
            req.goal_id = task_id or ""
            req.reason = "operator dashboard cancel"
            return self._call_sync(self._cli_cancel, req, _SERVICE_TIMEOUT_SEC)

        def call_dock(self, station_id: str | None, timeout_sec: float) -> dict[str, Any]:
            if not self._cli_get_charger.wait_for_service(timeout_sec=2.0):
                return {"success": False, "error": "get_nearest_charger service unavailable"}
            charger_req = GetNearestCharger.Request()
            charger_req.prefer_available_only = True
            charger_result = self._call_sync(
                self._cli_get_charger, charger_req, _SERVICE_TIMEOUT_SEC
            )
            if not charger_result.get("found"):
                return {
                    "success": False,
                    "error": charger_result.get("message", "no charger found"),
                }
            if station_id and charger_result.get("charger_id") != station_id:
                return {
                    "success": False,
                    "error": f"requested charger '{station_id}' is not the nearest available",
                }
            pose = charger_result["_charger_pose"]
            return self.call_navigate(pose.pose.position.x, pose.pose.position.y, None, timeout_sec)

        def _call_sync(self, client, request, timeout_sec: float) -> dict[str, Any]:
            future = client.call_async(request)
            deadline = time.monotonic() + timeout_sec
            while not future.done():
                if time.monotonic() > deadline:
                    return {"success": False, "error": "service call timed out"}
                time.sleep(0.02)
            try:
                response = future.result()
            except Exception as exc:
                return {"success": False, "error": str(exc)}
            return self._response_to_dict(response)

        @staticmethod
        def _response_to_dict(response) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for field_name in response.get_fields_and_field_types():
                value = getattr(response, field_name)
                if hasattr(value, "get_fields_and_field_types"):
                    # Keep complex fields (e.g. charger_pose) accessible to
                    # internal callers (call_dock) without flattening them
                    # into the JSON-safe response.
                    result[f"_{field_name}"] = value
                    continue
                result[field_name] = value
            return result
