"""bonbon_edge_ai_runtime.nodes.edge_ai_runtime_node -- Edge AI Runtime
brief Phase 10/12. The one genuinely new ROS2 node this package needs:
owns the real, persistent TaskRouter/SafetySeparationGuard/CacheManager/
ResourceGuard/InferenceScheduler singletons on the AI Pi (Pi-2) and
periodically republishes their status as JSON on 6 topics, matching the
6 WebSocket channels Phase 12 names
(/ws/edge-ai/{status,models,routes,resources,safety,cache}).

Follows the exact same lazy-rclpy-import, timer-tick,
std_msgs/String-JSON pattern already established by
bonbon_ai_model_registry.model_health_monitor's node entry point -- see
that file's own docstring for why (this dev sandbox has no rclpy, so
every node in this repo defers the import into main() rather than the
module top level).

This node does NOT make routing/safety decisions itself yet -- it only
publishes visibility. Wiring real AI-Pi callers (llm_orchestrator_node
etc.) to actually call TaskRouter/SafetySeparationGuard for every
request is the larger integration GAP-E8 documents as intentionally
deferred; this node exists so that integration has somewhere real to
report status once it happens, and so the dashboard has real (if
currently mostly-idle) data to show today rather than nothing.
"""

from __future__ import annotations

# SafetyState.CAUTION -- mirrors perception_efficiency_node's own
# _SAFETY_CAUTION=2 threshold (the real, live mechanism that already
# sheds perception load on CAUTION+, including the battery-low path via
# safety_state_machine's battery_caution_pct check).
SAFETY_CAUTION_LEVEL = 2
# No SafetyState received yet, or the last one is older than this --
# fail toward "assume caution" for this dashboard-facing value, matching
# this repo's established fail-closed posture (rule 13), rather than
# silently reporting False forever like the previous hardcoded default did.
SAFETY_STALE_SEC = 2.0


def derive_safety_caution_or_above(
    *, last_safety_level: int, last_safety_at: float, now: float, stale_after_sec: float = SAFETY_STALE_SEC
) -> bool:
    """Pure decision logic (18-point edge-AI verification, check 14) --
    module-level, no rclpy dependency, so it's directly unit-testable.
    `last_safety_at <= 0.0` means no message has ever been received."""
    age_sec = now - last_safety_at
    known_and_fresh = last_safety_at > 0.0 and age_sec <= stale_after_sec
    if not known_and_fresh:
        return True
    return last_safety_level >= SAFETY_CAUTION_LEVEL


def main(args: list[str] | None = None) -> None:  # pragma: no cover -- exercised only with rclpy present
    try:
        import time

        import json

        import rclpy
        from bonbon_msgs.msg import SafetyState
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "edge_ai_runtime_node requires rclpy + std_msgs + bonbon_msgs -- run inside a ROS2 "
            "environment, not this dev sandbox (see docs/EDGE_AI_CURRENT_STATE_AUDIT.md's environment note)"
        ) from exc

    _QOS_SAFETY = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
    )

    from bonbon_edge_ai_runtime.cache_manager import CacheManager
    from bonbon_edge_ai_runtime.config_loader import EdgeAIConfig
    from bonbon_edge_ai_runtime.dashboard_publisher import EdgeAIDashboardPublisher
    from bonbon_edge_ai_runtime.inference_scheduler import InferenceScheduler
    from bonbon_edge_ai_runtime.metrics_publisher import MetricsPublisher
    from bonbon_edge_ai_runtime.model_registry import load_merged
    from bonbon_edge_ai_runtime.resource_guard import ResourceGuard
    from bonbon_edge_ai_runtime.runtime_selector import ModelRuntimeSelector
    from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard
    from bonbon_edge_ai_runtime.task_router import TaskRouter

    class EdgeAIRuntimeNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("edge_ai_runtime_node")
            self.declare_parameter("publish_interval_sec", 2.0)

            self._config = EdgeAIConfig.load()
            self._registry = load_merged()
            self._selector = ModelRuntimeSelector(self._registry)
            self._safety_guard = SafetySeparationGuard()
            self._cache_manager = CacheManager()
            self._resource_guard = ResourceGuard()
            self._scheduler = InferenceScheduler()
            self._router = TaskRouter(safety_guard=self._safety_guard, cache_manager=self._cache_manager)
            self._metrics_pub = MetricsPublisher(
                cache_manager=self._cache_manager,
                scheduler=self._scheduler,
                resource_guard=self._resource_guard,
                safety_guard=self._safety_guard,
            )
            self._dashboard = EdgeAIDashboardPublisher(
                registry=self._registry,
                selector=self._selector,
                cache_manager=self._cache_manager,
                resource_guard=self._resource_guard,
                safety_guard=self._safety_guard,
                scheduler=self._scheduler,
                config=self._config,
            )
            self._last_route = None
            self._last_safety_state_name = "UNKNOWN"
            self._last_safety_level = -1
            self._last_safety_at = 0.0
            self.create_subscription(SafetyState, "/bonbon/safety/state", self._on_safety, _QOS_SAFETY)

            self._pubs = {
                "status": self.create_publisher(String, "/bonbon/edge_ai/status", 10),
                "models": self.create_publisher(String, "/bonbon/edge_ai/models", 10),
                "routes": self.create_publisher(String, "/bonbon/edge_ai/routes", 10),
                "resources": self.create_publisher(String, "/bonbon/edge_ai/resources", 10),
                "safety": self.create_publisher(String, "/bonbon/edge_ai/safety", 10),
                "cache": self.create_publisher(String, "/bonbon/edge_ai/cache", 10),
            }

            interval = self.get_parameter("publish_interval_sec").get_parameter_value().double_value
            self.create_timer(interval, self._tick)
            self.get_logger().info("edge_ai_runtime_node started -- publishing status every %.1fs" % interval)

        def _on_safety(self, msg) -> None:
            self._last_safety_state_name = msg.state_name
            self._last_safety_level = int(msg.state)
            self._last_safety_at = time.monotonic()

        def _tick(self) -> None:
            # Real CPU/thermal readings would come from
            # /bonbon/system/resource_usage in a full integration; this
            # node reads 0.0 for temp_c honestly (never fabricates a
            # sensor value) until that subscription is wired in a future
            # pass -- resource_guard.evaluate() still reports real
            # CPU/RAM via psutil regardless.
            #
            # safety_caution_or_above now reflects the real /bonbon/safety/state
            # subscription (18-point edge-AI verification, check 14) --
            # previously hardcoded False here regardless of real safety
            # state, meaning this node's own resource_guard dashboard view
            # never reflected CAUTION+ (including the battery-low path,
            # which safety_state_machine.py escalates to CAUTION).
            safety_caution_or_above = derive_safety_caution_or_above(
                last_safety_level=self._last_safety_level,
                last_safety_at=self._last_safety_at,
                now=time.monotonic(),
            )
            snapshot = self._metrics_pub.snapshot(
                temp_c=0.0,
                safety_state_name=self._last_safety_state_name,
                safety_caution_or_above=safety_caution_or_above,
            )
            self._publish_json("status", self._dashboard.overview_view(snapshot=snapshot, active_route=self._last_route))
            self._publish_json("models", self._dashboard.registry_view())
            self._publish_json("routes", {"lastRoute": self._last_route.to_dict() if self._last_route else None})
            self._publish_json("resources", self._dashboard.resource_guard_view(snapshot=snapshot))
            self._publish_json("safety", self._dashboard.safety_separation_view())
            self._publish_json("cache", self._dashboard.cache_view())

        def _publish_json(self, channel: str, payload: dict) -> None:
            msg = String()
            try:
                msg.data = json.dumps(payload, default=str)
            except (TypeError, ValueError) as exc:
                msg.data = json.dumps({"available": False, "message": f"serialization error: {exc}"})
            self._pubs[channel].publish(msg)

    rclpy.init(args=args)
    node = EdgeAIRuntimeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
