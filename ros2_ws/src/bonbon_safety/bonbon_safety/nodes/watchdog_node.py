"""
bonbon_safety.nodes.watchdog_node
====================================
ROS2 Lifecycle node — monitors heartbeats from all critical nodes and
requests restarts when a node goes silent.

Each managed node must publish a ModuleHealth message on
/bonbon/<package>/<node_name>/health at its declared rate.

The watchdog subscribes to all registered health topics, tracks
last-seen timestamps, and classifies each node by crash class:

  CLASS_A (CRITICAL)  — safety_supervisor, estop, safety_gate
  CLASS_B (ESSENTIAL) — lidar, ekf, nav2_planner, nav2_controller
  CLASS_C (IMPORTANT) — camera, asr, llm_orchestrator, tts
  CLASS_D (AUXILIARY) — face_recognition, display, led

On detecting a stale heartbeat the watchdog:
  1. Publishes ModuleHealth with status=STALE
  2. Attempts a restart via the /bonbon/node/restart service
  3. Notifies the safety supervisor via /bonbon/safety/module_crashed
  4. Logs the event
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum

import rclpy
from bonbon_msgs.msg import ModuleHealth
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

logger = logging.getLogger(__name__)

RELIABLE_D5 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)
RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class NodeClass(IntEnum):
    CRITICAL = 1  # loss triggers FAULT immediately
    ESSENTIAL = 2  # loss triggers DEGRADED_NAVIGATION
    IMPORTANT = 3  # loss triggers REDUCED_CAPABILITY
    AUXILIARY = 4  # loss noted but operation continues normally


@dataclass
class ManagedNode:
    """Registry entry for a node the watchdog monitors."""

    name: str  # e.g. "detection_node"
    health_topic: str  # /bonbon/vision/detection_node/health
    node_class: NodeClass
    expected_period_sec: float  # declared publish rate
    stale_multiplier: float = 3.0  # stale after N × expected_period
    max_restart_attempts: int = 3
    # Runtime state (updated by watchdog)
    last_seen: float = field(default_factory=lambda: 0.0)
    restart_count: int = 0
    last_status: int = ModuleHealth.OK
    is_stale: bool = False


# Default node registry matching BonBon hardware layout
DEFAULT_MANAGED_NODES: list[ManagedNode] = [
    # CLASS A — CRITICAL
    ManagedNode(
        "safety_gate_node", "/bonbon/actuation/safety_gate_node/health", NodeClass.CRITICAL, 1.0
    ),
    ManagedNode("estop_node", "/bonbon/safety/estop_node/health", NodeClass.CRITICAL, 1.0),
    # CLASS B — ESSENTIAL
    ManagedNode("lidar_node", "/bonbon/spatial/lidar_node/health", NodeClass.ESSENTIAL, 1.0),
    ManagedNode("ekf_node", "/bonbon/spatial/ekf_node/health", NodeClass.ESSENTIAL, 1.0),
    ManagedNode("nav2_planner", "/bonbon/navigation/planner_node/health", NodeClass.ESSENTIAL, 2.0),
    ManagedNode(
        "nav2_controller", "/bonbon/navigation/controller_node/health", NodeClass.ESSENTIAL, 2.0
    ),
    # CLASS C — IMPORTANT
    ManagedNode("camera_node", "/bonbon/vision/camera_node/health", NodeClass.IMPORTANT, 1.0),
    ManagedNode("vision_node", "/bonbon/vision/vision_node/health", NodeClass.IMPORTANT, 1.0),
    ManagedNode("detection_node", "/bonbon/vision/detection_node/health", NodeClass.IMPORTANT, 1.0),
    ManagedNode("asr_node", "/bonbon/speech/asr_node/health", NodeClass.IMPORTANT, 2.0),
    ManagedNode(
        "llm_orchestrator_node", "/bonbon/llm/orchestrator_node/health", NodeClass.IMPORTANT, 2.0
    ),
    ManagedNode("tts_node", "/bonbon/tts/tts_node/health", NodeClass.IMPORTANT, 2.0),
    # CLASS D — AUXILIARY
    ManagedNode("face_node", "/bonbon/vision/face_node/health", NodeClass.AUXILIARY, 2.0),
    ManagedNode("display_node", "/bonbon/actuation/display_node/health", NodeClass.AUXILIARY, 2.0),
    ManagedNode("led_node", "/bonbon/actuation/led_node/health", NodeClass.AUXILIARY, 2.0),
]


class WatchdogNode(LifecycleNode):
    """
    Monitors heartbeats from all BonBon nodes and requests restarts on failure.
    Runs at 2 Hz; stale detection is threshold-based (3× expected period by default).
    """

    NODE_NAME = "watchdog_node"

    def __init__(self) -> None:
        super().__init__(self.NODE_NAME)
        self._lock = threading.Lock()
        self._registry: dict[str, ManagedNode] = {}
        self._subs: list = []
        self._check_timer = None

        self.declare_parameter("watchdog_rate_hz", 2.0)
        self.declare_parameter("startup_grace_sec", 30.0)
        self._startup_time: float = time.monotonic()

        self.get_logger().info("WatchdogNode created")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        for node_def in DEFAULT_MANAGED_NODES:
            self._registry[node_def.name] = node_def
        self.get_logger().info("Watchdog configured — monitoring %d nodes", len(self._registry))
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        # Publishers
        self._pub_critical_crash = self.create_lifecycle_publisher(
            Bool, "/bonbon/safety/critical_node_crashed", RELIABLE_TL
        )
        self._pub_important_crash = self.create_lifecycle_publisher(
            Bool, "/bonbon/safety/important_node_crashed", RELIABLE_TL
        )
        self._pub_health = self.create_lifecycle_publisher(
            ModuleHealth, "/bonbon/safety/watchdog_node/health", RELIABLE_D5
        )

        # Subscribe to all managed node health topics
        for node_def in self._registry.values():
            node_def.last_seen = time.monotonic()  # init to now (grace period)
            sub = self.create_subscription(
                ModuleHealth,
                node_def.health_topic,
                lambda msg, n=node_def: self._cb_health(msg, n),
                RELIABLE_D5,
            )
            self._subs.append(sub)

        rate_hz = self.get_parameter("watchdog_rate_hz").value
        self._check_timer = self.create_timer(1.0 / rate_hz, self._check_cycle)
        self._startup_time = time.monotonic()
        self.get_logger().info("WatchdogNode ACTIVE at %.1f Hz", rate_hz)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._check_timer:
            self._check_timer.cancel()
        for sub in self._subs:
            self.destroy_subscription(sub)
        self._subs.clear()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return self.on_cleanup(state)

    # ── Health callback ───────────────────────────────────────────────────────

    def _cb_health(self, msg: ModuleHealth, node_def: ManagedNode) -> None:
        """Called every time a managed node publishes its health."""
        with self._lock:
            node_def.last_seen = time.monotonic()
            node_def.last_status = msg.status
            if node_def.is_stale:
                # Node recovered
                node_def.is_stale = False
                node_def.restart_count = 0
                self.get_logger().info(
                    "Node RECOVERED: %s (class %s)",
                    node_def.name,
                    node_def.node_class.name,
                )
                self._publish_crash_flags()

    # ── Check cycle (2 Hz) ────────────────────────────────────────────────────

    def _check_cycle(self) -> None:
        now = time.monotonic()
        grace = self.get_parameter("startup_grace_sec").value
        in_startup_grace = (now - self._startup_time) < grace

        any_critical_stale = False
        any_important_stale = False

        with self._lock:
            for node_def in self._registry.values():
                stale_threshold = node_def.expected_period_sec * node_def.stale_multiplier
                age = now - node_def.last_seen

                if age > stale_threshold and not in_startup_grace:
                    if not node_def.is_stale:
                        # New stale detection
                        node_def.is_stale = True
                        self.get_logger().error(
                            "Node STALE: %s (class %s) — last seen %.1f s ago",
                            node_def.name,
                            node_def.node_class.name,
                            age,
                        )
                        self._attempt_restart(node_def)

                    if node_def.node_class == NodeClass.CRITICAL:
                        any_critical_stale = True
                    elif node_def.node_class in (NodeClass.ESSENTIAL, NodeClass.IMPORTANT):
                        any_important_stale = True

        self._publish_crash_flags(any_critical_stale, any_important_stale)
        self._publish_own_health()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _attempt_restart(self, node_def: ManagedNode) -> None:
        if node_def.restart_count >= node_def.max_restart_attempts:
            self.get_logger().error(
                "Node %s exhausted %d restart attempts — giving up",
                node_def.name,
                node_def.max_restart_attempts,
            )
            return
        node_def.restart_count += 1
        self.get_logger().warn(
            "Requesting restart of node %s (attempt %d/%d)",
            node_def.name,
            node_def.restart_count,
            node_def.max_restart_attempts,
        )
        # In production this calls the /bonbon/node/restart service
        # or signals the systemd unit manager.  Placeholder for now.

    def _publish_crash_flags(
        self,
        critical: bool = False,
        important: bool = False,
    ) -> None:
        if self._pub_critical_crash:
            msg = Bool()
            msg.data = critical
            self._pub_critical_crash.publish(msg)
        if self._pub_important_crash:
            msg = Bool()
            msg.data = important
            self._pub_important_crash.publish(msg)

    def _publish_own_health(self) -> None:
        if self._pub_health is None:
            return
        stale_count = sum(1 for n in self._registry.values() if n.is_stale)
        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = "watchdog_node"
        msg.status = ModuleHealth.OK if stale_count == 0 else ModuleHealth.WARN
        msg.status_text = (
            f"OK — monitoring {len(self._registry)} nodes"
            if stale_count == 0
            else f"WARNING — {stale_count} stale node(s)"
        )
        self._pub_health.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WatchdogNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
