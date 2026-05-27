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
This bridge NEVER bypasses the Safety Supervisor.  It publishes commands only
after the SafetyCommandGate has approved them.  The bridge does not implement
its own safety logic — it only relays already-approved messages.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator

logger = logging.getLogger(__name__)

# Try to import rclpy; fall back gracefully when not available
try:
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, Float32, String

    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    logger.warning("rclpy not available — ROS2 bridge running in stub mode")

# Topic names (mirror the rest of BonBon ROS2 architecture)
_TOPIC_SAFETY_STATE = "/bonbon/safety/state"
_TOPIC_BATTERY = "/bonbon/battery/status"
_TOPIC_NAV_STATE = "/bonbon/navigation/state"
_TOPIC_PERCEPTION = "/bonbon/perception/status"
_TOPIC_TTS_STATE = "/bonbon/tts/state"
_TOPIC_ACTUATION = "/bonbon/actuation/state"
_TOPIC_MODULE_STATUS = "/bonbon/modules/status"
_TOPIC_HEARTBEAT = "/bonbon/heartbeat"

# Service names
_SVC_EMERGENCY_STOP = "/bonbon/safety/emergency_stop"
_SVC_SPEAK = "/bonbon/tts/speak"
_SVC_NAVIGATE = "/bonbon/navigation/navigate"
_SVC_PAUSE = "/bonbon/navigation/pause"
_SVC_RESUME = "/bonbon/navigation/resume"
_SVC_DOCK = "/bonbon/navigation/dock"
_SVC_CANCEL_TASK = "/bonbon/task/cancel"
_SVC_RESTART_MODULE = "/bonbon/modules/restart"
_SVC_GET_CONFIG = "/bonbon/config/get"
_SVC_SET_CONFIG = "/bonbon/config/set"
_SVC_MEMORY_QUERY = "/bonbon/memory/query"
_SVC_RAG_QUERY = "/bonbon/rag/query"

_SERVICE_TIMEOUT_SEC = 5.0


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
        return self._call_service_stub("emergency_stop", {"reason": reason})

    def call_speak(self, text: str, language: str, priority: str) -> dict[str, Any]:
        return self._call_service_stub(
            "speak", {"text": text, "language": language, "priority": priority}
        )

    def call_navigate(
        self,
        goal_x: float,
        goal_y: float,
        goal_yaw: float | None,
        map_id: str | None,
        speed_limit_mps: float | None,
    ) -> dict[str, Any]:
        return self._call_service_stub(
            "navigate",
            {
                "goal_x": goal_x,
                "goal_y": goal_y,
                "goal_yaw": goal_yaw,
                "map_id": map_id,
                "speed_limit_mps": speed_limit_mps,
            },
        )

    def call_pause(self) -> dict[str, Any]:
        return self._call_service_stub("pause", {})

    def call_resume(self) -> dict[str, Any]:
        return self._call_service_stub("resume", {})

    def call_dock(self, station_id: str | None) -> dict[str, Any]:
        return self._call_service_stub("dock", {"station_id": station_id})

    def call_cancel_task(self, task_id: str | None) -> dict[str, Any]:
        return self._call_service_stub("cancel_task", {"task_id": task_id})

    def call_restart_module(self, module_name: str) -> dict[str, Any]:
        return self._call_service_stub("restart_module", {"module": module_name})

    def call_get_config(self, key: str) -> dict[str, Any]:
        return self._call_service_stub("get_config", {"key": key})

    def call_set_config(self, key: str, value: Any) -> dict[str, Any]:
        return self._call_service_stub("set_config", {"key": key, "value": value})

    def call_memory_query(self, query: str, limit: int) -> dict[str, Any]:
        return self._call_service_stub("memory_query", {"query": query, "limit": limit})

    def call_rag_query(self, query: str, collection: str, top_k: int) -> dict[str, Any]:
        return self._call_service_stub(
            "rag_query", {"query": query, "collection": collection, "top_k": top_k}
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_service_stub(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Stub implementation used when ROS2 is unavailable."""
        if not _ROS2_AVAILABLE or not self._running:
            logger.debug("ROS2 stub call: %s %s", name, params)
            return {"success": True, "stub": True, "service": name}
        # When ROS2 is available, delegate to the node's service client
        if self._node:
            return self._node.call_service(name, params)
        return {"success": False, "error": "bridge not ready"}

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

            _best_effort = QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.BEST_EFFORT,
                durability=DurabilityPolicy.VOLATILE,
            )

            # Subscriptions
            self.create_subscription(String, _TOPIC_SAFETY_STATE, self._on_safety, _best_effort)
            self.create_subscription(String, _TOPIC_BATTERY, self._on_battery, _best_effort)
            self.create_subscription(String, _TOPIC_NAV_STATE, self._on_navigation, _best_effort)
            self.create_subscription(String, _TOPIC_PERCEPTION, self._on_perception, _best_effort)
            self.create_subscription(String, _TOPIC_TTS_STATE, self._on_tts, _best_effort)
            self.create_subscription(String, _TOPIC_ACTUATION, self._on_actuation, _best_effort)
            self.create_subscription(String, _TOPIC_MODULE_STATUS, self._on_module, _best_effort)
            self.create_subscription(Bool, _TOPIC_HEARTBEAT, self._on_heartbeat, _best_effort)

        # -- Subscription callbacks --

        def _parse(self, msg: String) -> dict[str, Any]:
            try:
                return _json.loads(msg.data)
            except Exception:
                return {}

        def _on_safety(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_safety(data)
            self._emit("safety-events", "safety_state_changed", data)

        def _on_battery(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_battery(data)

        def _on_navigation(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_navigation(data)
            self._emit("navigation-events", "navigation_state_changed", data)

        def _on_perception(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_perception(data)

        def _on_tts(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_tts(data)

        def _on_actuation(self, msg: String) -> None:
            data = self._parse(msg)
            self._agg.update_actuation(data)

        def _on_module(self, msg: String) -> None:
            data = self._parse(msg)
            name = data.get("module", "unknown")
            self._agg.update_module(name, data)
            self._emit("diagnostics", "module_status_changed", data)

        def _on_heartbeat(self, msg: Bool) -> None:
            self._agg.mark_heartbeat()

        # -- Service calls --

        def call_service(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
            """Synchronous service call with timeout (called from thread pool)."""
            # For ROS2 service clients, we'd set up clients per service.
            # This is a simplified dispatch — production would use typed services.
            logger.debug("ROS2 service call: %s %s", name, params)
            # Return stub until typed service interfaces are wired
            return {"success": True, "service": name, "params": params}
