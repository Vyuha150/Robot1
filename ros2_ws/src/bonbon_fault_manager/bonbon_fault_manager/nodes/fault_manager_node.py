"""bonbon_fault_manager.nodes.fault_manager_node
====================================================
Aggregates raw hardware/safety signals into the classified fault
registry (see core/fault_registry.py, core/component_rules.py) and
publishes it for bonbon_operator_api's dashboard to consume.

Subscribes:
  /bonbon/hal/fault      (bonbon_msgs/HalFault)   -- every HAL node already
                          publishes here on driver fault/recovery
                          (see bonbon_hal/base/health_reporter.py); this
                          node does not duplicate any HAL polling, it only
                          classifies events HAL nodes already emit.
  /bonbon/safety/state   (bonbon_msgs/SafetyState) -- TRANSIENT_LOCAL, so
                          a late-starting fault_manager gets current state
                          immediately, same as every other SafetyState
                          subscriber in this repo.
  /bonbon/system/failure_events (bonbon_msgs/SafetyEvent) -- REAL,
                          already-published by
                          bonbon_distributed_safety.distributed_safety_node
                          on every peer-Pi link-state transition (that
                          detection already exists and is tested); this
                          node only relays the pi_link_state_change ones
                          into the unified dashboard registry, which
                          previously never saw them at all.

Publishes:
  /bonbon/fault_manager/registry (bonbon_msgs/ComponentFaultArray) --
                          TRANSIENT_LOCAL, republished on every update AND
                          on a periodic timer so a late-joining dashboard
                          client always has current state without racing
                          the next fault event.

Deliberately does NOT re-implement node-liveness/heartbeat monitoring --
that is bonbon_safety.nodes.watchdog_node's job already. This node
answers "which physical COMPONENT is broken, how bad, and what do I do
about it," not "which ROS2 node process is still alive."

NOTE: imports rclpy/bonbon_msgs, not importable/testable in this dev
sandbox -- syntax-checked via py_compile only. All decision logic lives
in core/fault_taxonomy.py, core/component_rules.py, core/fault_registry.py
(48 unit tests, fully verified there).
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import (
    ComponentFault,
    ComponentFaultArray,
    HalFault,
    SafetyEvent,
    SafetyState,
)
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from bonbon_fault_manager.core.fault_registry import FaultRecord, FaultRegistry

_QOS_RELIABLE_D10 = QoSProfile(
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
# Matches distributed_safety_node.py's own _QOS_RELIABLE publisher QoS
# for /bonbon/system/failure_events exactly (RELIABLE/VOLATILE/depth-20).
_QOS_RELIABLE_D20 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=20,
)


class FaultManagerNode(LifecycleNode):
    def __init__(self, node_name: str = "fault_manager_node") -> None:
        super().__init__(node_name)
        self.declare_parameter("republish_rate_hz", 1.0)

        self._registry = FaultRegistry()
        self._sub_hal_fault = None
        self._sub_safety_state = None
        self._sub_failure_events = None
        self._pub_registry = None
        self._timer = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("FaultManagerNode configuring …")
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self._sub_hal_fault = self.create_subscription(
            HalFault, "/bonbon/hal/fault", self._on_hal_fault, _QOS_RELIABLE_D10
        )
        self._sub_safety_state = self.create_subscription(
            SafetyState, "/bonbon/safety/state", self._on_safety_state, _QOS_TRANSIENT
        )
        self._sub_failure_events = self.create_subscription(
            SafetyEvent,
            "/bonbon/system/failure_events",
            self._on_failure_event,
            _QOS_RELIABLE_D20,
        )
        self._pub_registry = self.create_lifecycle_publisher(
            ComponentFaultArray, "/bonbon/fault_manager/registry", _QOS_TRANSIENT
        )

        rate = float(self.get_parameter("republish_rate_hz").get_parameter_value().double_value)
        self._timer = self.create_timer(1.0 / (rate or 1.0), self._publish_registry)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._timer is not None:
            self._timer.cancel()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._sub_hal_fault = None
        self._sub_safety_state = None
        self._sub_failure_events = None
        self._pub_registry = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return self.on_cleanup(state)

    # ── Callbacks ────────────────────────────────────────────────────────

    def _on_hal_fault(self, msg: HalFault) -> None:
        self._registry.update_from_hal_fault(
            device=msg.device,
            error_code=msg.error_code,
            message=msg.message,
            severity=msg.severity,
            is_recovered=msg.is_recovered,
        )
        self._publish_registry()

    def _on_safety_state(self, msg: SafetyState) -> None:
        self._registry.update_safety_supervisor(
            msg.state_name, msg.reason, msg.requires_manual_reset
        )
        self._registry.sync_degraded_modules(list(msg.degraded_modules), reason=msg.reason)
        self._publish_registry()

    def _on_failure_event(self, msg: SafetyEvent) -> None:
        # update_from_pi_link_event() itself ignores every SafetyEvent
        # that isn't a pi_link_state_change (returns None, no-op) -- this
        # node deliberately does not react to every SafetyEvent trigger,
        # only the one bonbon_distributed_safety publishes that this
        # registry previously had no path for. Republish on ANY
        # pi_link_state_change, not just when a record is returned -- a
        # peer coming back online also returns None (the record is
        # REMOVED, not updated), and that removal is exactly the kind of
        # change the dashboard needs to see promptly, not just on the
        # next periodic republish_registry() tick.
        self._registry.update_from_pi_link_event(
            msg.trigger_name, msg.description, msg.new_state_name
        )
        if msg.trigger_name == "pi_link_state_change":
            self._publish_registry()

    # ── Publish ──────────────────────────────────────────────────────────

    def _publish_registry(self) -> None:
        if self._pub_registry is None:
            return
        msg = ComponentFaultArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "fault_manager"
        msg.components = [self._to_msg(r) for r in self._registry.snapshot()]
        msg.worst_level = int(self._registry.worst_level())
        self._pub_registry.publish(msg)

    def _to_msg(self, record: FaultRecord) -> ComponentFault:
        m = ComponentFault()
        # last_seen reflects "as of this publish," not the exact fault
        # wall-clock time -- the registry tracks fault recency with
        # time.monotonic() (for testability, see fault_registry.py), which
        # has no meaningful conversion to a wall-clock builtin_interfaces/Time.
        m.header.stamp = self.get_clock().now().to_msg()
        m.last_seen = m.header.stamp
        m.component_id = record.component_id
        m.subsystem = record.subsystem
        m.affected_pi = record.affected_pi
        m.fault_level = int(record.fault_level)
        m.error_code = record.error_code
        m.message = record.message
        m.recovery_action = record.recovery_action
        m.dashboard_visible = record.dashboard_visible
        m.occurrence_count = record.occurrence_count
        return m


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = FaultManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
