"""KioskROS2Bridge — the only place this package talks to ROS2.

Design mirrors bonbon_operator_api/ros2/ros2_bridge.py:
* rclpy is imported conditionally so the API runs without a live ROS2
  environment (unit tests, CI, frontend-only demos).
* The executor runs in a dedicated background daemon thread.
* Service calls block a thread-pool worker, which is acceptable for the
  low request volume a reception kiosk generates.

Safety contract
---------------
This bridge NEVER bypasses bonbon_llm's safety stack or bonbon_navigation's
safety-gated velocity pipeline. It only calls the same services
bonbon_operator_api already calls (`/navigation/navigate_to`) plus the
LLM's own synchronous query service (`/llm/query`) and the privacy-mode
service (`/bonbon/privacy/set_mode`). It never publishes to `/cmd_vel`,
never talks to actuators, and never live-writes bonbon_navigation's
named-location registry — the Facility Map Editor is export-only.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

try:
    import rclpy
    from bonbon_msgs.msg import TTSRequest
    from bonbon_srvs.srv import LLMQuery, NavigateTo, SetPrivacyMode
    from geometry_msgs.msg import PoseStamped
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — kiosk ROS2 bridge running in stub mode")

# Service/topic names — verified against the owning packages' real
# publishers/servers (bonbon_llm, bonbon_navigation, bonbon_affective_ai, bonbon_tts).
_SVC_LLM_QUERY = "/llm/query"  # bonbon_llm/llm_orchestrator_node
_SVC_NAVIGATE = "/navigation/navigate_to"  # bonbon_navigation/navigation_node
_SVC_SET_PRIVACY_MODE = "/bonbon/affective/set_privacy_mode"  # bonbon_affective_ai/affective_ai_node
_TOPIC_TTS_REQUEST = "/bonbon/tts/request"

_SERVICE_TIMEOUT_SEC = 5.0


class BridgeError(Exception):
    def __init__(self, message: str, code: str = "BRIDGE_ERROR") -> None:
        super().__init__(message)
        self.code = code


class KioskROS2Bridge:
    def __init__(
        self,
        node_name: str = "bonbon_patient_kiosk_bridge",
        navigate_timeout_sec: float = 130.0,
        llm_query_timeout_sec: float = 35.0,
    ) -> None:
        self._node_name = node_name
        self._navigate_timeout_sec = navigate_timeout_sec
        self._llm_query_timeout_sec = llm_query_timeout_sec
        self._node = None
        self._executor = None
        self._spin_thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _ROS2_AVAILABLE:
            logger.warning("ROS2 not available — bridge not started")
            return
        if self._running:
            return
        try:
            if not rclpy.ok():
                rclpy.init()
            self._node = _KioskNode(self._node_name)
            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)
            self._spin_thread = threading.Thread(
                target=self._spin_loop, daemon=True, name="kiosk-ros2-bridge-spin"
            )
            self._running = True
            self._spin_thread.start()
            logger.info("Kiosk ROS2 bridge started (node=%s)", self._node_name)
        except Exception as exc:
            logger.error("Kiosk ROS2 bridge start failed: %s", exc)
            self._running = False

    def stop(self) -> None:
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
        logger.info("Kiosk ROS2 bridge stopped")

    def _spin_loop(self) -> None:
        try:
            self._executor.spin()
        except Exception as exc:
            if self._running:
                logger.error("Kiosk ROS2 bridge spin error: %s", exc)

    def _ready(self) -> bool:
        return _ROS2_AVAILABLE and self._running and self._node is not None

    # ------------------------------------------------------------------
    # Public calls
    # ------------------------------------------------------------------

    def call_llm_query(
        self, query_text: str, speaker_id: str, context_json: str = "", require_grounding: bool = False
    ) -> dict[str, Any]:
        # NOTE: bonbon_llm's README documents /llm/query (LLMQuery.srv) as its
        # synchronous query service, but llm_orchestrator_node does not yet
        # create a server for it (verified: only referenced in bonbon_llm's
        # own test mocks, no create_service call anywhere in that package).
        # wait_for_service below will honestly report "unavailable" until
        # that server exists — chat_api.py must degrade gracefully on this,
        # never treat a timeout as a crash.
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_llm_query(
            query_text, speaker_id, context_json, require_grounding, self._llm_query_timeout_sec
        )

    def call_navigate(self, named_location: str, requester_id: str, enqueue: bool = False) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_navigate(
            named_location, requester_id, enqueue, self._navigate_timeout_sec
        )

    def call_set_privacy_mode(self, enabled: bool, level: str, operator_id: str) -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.call_set_privacy_mode(enabled, level, operator_id)

    def publish_speak(self, text: str, priority: str = "normal", language: str = "") -> dict[str, Any]:
        if not self._ready():
            return {"success": False, "error": "bridge not ready"}
        return self._node.publish_speak(text, priority, language)


if _ROS2_AVAILABLE:

    class _KioskNode(Node):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            _best_effort = QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )
            self._cli_llm_query = self.create_client(LLMQuery, _SVC_LLM_QUERY)
            self._cli_navigate = self.create_client(NavigateTo, _SVC_NAVIGATE)
            self._cli_privacy = self.create_client(SetPrivacyMode, _SVC_SET_PRIVACY_MODE)
            self._pub_tts_request = self.create_publisher(
                TTSRequest, _TOPIC_TTS_REQUEST, _best_effort
            )

        def call_llm_query(
            self,
            query_text: str,
            speaker_id: str,
            context_json: str,
            require_grounding: bool,
            timeout_sec: float,
        ) -> dict[str, Any]:
            if not self._cli_llm_query.wait_for_service(timeout_sec=2.0):
                return {"success": False, "error": "llm/query service unavailable"}
            req = LLMQuery.Request()
            req.query_text = query_text
            req.speaker_id = speaker_id
            req.context_json = context_json
            req.timeout_sec = float(timeout_sec)
            req.require_grounding = require_grounding
            return self._call_sync(self._cli_llm_query, req, timeout_sec)

        def call_navigate(
            self, named_location: str, requester_id: str, enqueue: bool, timeout_sec: float
        ) -> dict[str, Any]:
            if not self._cli_navigate.wait_for_service(timeout_sec=2.0):
                return {"success": False, "error": "navigate_to service unavailable"}
            req = NavigateTo.Request()
            req.goal_id = str(uuid.uuid4())
            req.named_location = named_location
            req.target_pose = PoseStamped()
            req.timeout_sec = float(timeout_sec)
            req.enqueue = enqueue
            req.requester_id = requester_id
            return self._call_sync(self._cli_navigate, req, timeout_sec)

        def call_set_privacy_mode(self, enabled: bool, level: str, operator_id: str) -> dict[str, Any]:
            if not self._cli_privacy.wait_for_service(timeout_sec=1.0):
                return {"success": False, "error": "SetPrivacyMode service unavailable"}
            req = SetPrivacyMode.Request()
            req.enabled = enabled
            req.level = level
            req.operator_id = operator_id
            return self._call_sync(self._cli_privacy, req, _SERVICE_TIMEOUT_SEC)

        def publish_speak(self, text: str, priority: str, language: str) -> dict[str, Any]:
            _PRIORITY_MAP = {"low": 1, "normal": 5, "high": 10}
            msg = TTSRequest()
            msg.text = text
            msg.priority = _PRIORITY_MAP.get((priority or "normal").lower(), 5)
            msg.language = language or ""
            msg.request_id = str(uuid.uuid4())
            msg.speed_factor = 1.0
            self._pub_tts_request.publish(msg)
            return {"success": True, "request_id": msg.request_id}

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
                    continue
                result[field_name] = value
            return result
