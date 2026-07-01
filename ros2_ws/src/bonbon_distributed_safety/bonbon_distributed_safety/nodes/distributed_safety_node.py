"""DistributedSafetyNode — publishes this Pi's own heartbeat and tracks the
other two Pis' liveness via HeartbeatMonitor.

Runs on all three Pis (self_id param differs per pi_*.yaml runtime
profile). Publishes:
    /bonbon/pi{N}/heartbeat            (bonbon_msgs/ModuleHealth) — own heartbeat, unconditional
    /bonbon/system/failure_events      (bonbon_msgs/SafetyEvent)  — on every link transition

Subscribes the OTHER two Pis' heartbeat topics.

This node deliberately does not decide behavior on peer loss — it only
detects and reports. bonbon_authority_manager consumes its link-state
output to apply config/distributed/failure_policy.yaml.

NOTE: this file imports rclpy/bonbon_msgs and cannot be executed or
pytest-run in this dev sandbox (no ROS2 install here) — see
docs/PERCEPTION_AI_CURRENT_AUDIT.md for why that constraint shaped this
session's package designs. It is syntax-checked via `python -m py_compile`
only. All safety-relevant logic lives in core/heartbeat_monitor.py, which
IS fully unit-tested (12 tests).
"""

from __future__ import annotations

import time

import rclpy
from bonbon_msgs.msg import ModuleHealth, SafetyEvent
from bonbon_srvs.srv import HealthCheck
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from bonbon_distributed_safety.core.heartbeat_monitor import HeartbeatConfig, HeartbeatMonitor, PiId

_SOURCE_MODULE = "bonbon_distributed_safety"
_ALL_PI_IDS = {"pi1": PiId.PI1, "pi2": PiId.PI2, "pi3": PiId.PI3}

_QOS_HEARTBEAT = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=20,
)


class DistributedSafetyNode(LifecycleNode):
    def __init__(self, node_name: str = "distributed_safety_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("self_id", "pi3")  # "pi1" | "pi2" | "pi3"
        self.declare_parameter("heartbeat_rate_hz", 2.0)
        self.declare_parameter("stale_after_sec", 1.5)
        self.declare_parameter("lost_after_sec", 5.0)

        self._monitor: HeartbeatMonitor | None = None
        self._self_id: PiId = PiId.PI3
        self._pub_heartbeat: LifecyclePublisher | None = None
        self._pub_failure_events: LifecyclePublisher | None = None
        self._subs: list = []
        self._heartbeat_timer = None
        self._eval_timer = None
        self._srv_health = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        gp = self.get_parameter
        self_id_str = gp("self_id").get_parameter_value().string_value
        self._self_id = _ALL_PI_IDS.get(self_id_str, PiId.PI3)
        cfg = HeartbeatConfig(
            stale_after_sec=float(gp("stale_after_sec").get_parameter_value().double_value),
            lost_after_sec=float(gp("lost_after_sec").get_parameter_value().double_value),
        )
        self._monitor = HeartbeatMonitor(self._self_id, config=cfg)

        self._pub_heartbeat = self.create_lifecycle_publisher(
            ModuleHealth, f"/bonbon/{self_id_str}/heartbeat", _QOS_HEARTBEAT
        )
        self._pub_failure_events = self.create_lifecycle_publisher(
            SafetyEvent, "/bonbon/system/failure_events", _QOS_RELIABLE
        )
        for peer in self._monitor.peers:
            self.create_subscription(
                ModuleHealth,
                f"/bonbon/{peer.value}/heartbeat",
                self._make_heartbeat_cb(peer),
                _QOS_HEARTBEAT,
            )
        self._srv_health = self.create_service(HealthCheck, "~/health_check", self._cb_health_check)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        rate = float(self.get_parameter("heartbeat_rate_hz").get_parameter_value().double_value)
        self._heartbeat_timer = self.create_timer(1.0 / rate, self._cb_publish_heartbeat)
        self._eval_timer = self.create_timer(0.5, self._cb_evaluate)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        for t in (self._heartbeat_timer, self._eval_timer):
            if t is not None:
                t.cancel()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._monitor = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _make_heartbeat_cb(self, peer: PiId):
        def _cb(msg: ModuleHealth) -> None:
            if self._monitor is not None:
                self._monitor.on_heartbeat(peer, now=time.monotonic())

        return _cb

    def _cb_publish_heartbeat(self) -> None:
        if self._pub_heartbeat is None:
            return
        msg = ModuleHealth()
        msg.module_name = _SOURCE_MODULE
        msg.status = 0  # OK — unconditional heartbeat regardless of local component health
        self._pub_heartbeat.publish(msg)

    def _cb_evaluate(self) -> None:
        if self._monitor is None or self._pub_failure_events is None:
            return
        transitions = self._monitor.evaluate(now=time.monotonic())
        for t in transitions:
            evt = SafetyEvent()
            evt.severity = (
                SafetyEvent.RESOLVED if t.new_state.value == "online" else SafetyEvent.WARNING
            )
            evt.trigger_name = "pi_link_state_change"
            evt.module_name = _SOURCE_MODULE
            evt.prior_state_name = t.previous_state.value
            evt.new_state_name = t.new_state.value
            evt.description = (
                f"{self._self_id.value} observed {t.pi.value}: "
                f"{t.previous_state.value} -> {t.new_state.value}"
            )
            self._pub_failure_events.publish(evt)
            self.get_logger().warning(evt.description)

    def _cb_health_check(self, request, response):
        response.healthy = self._monitor is not None
        response.status = "operational" if self._monitor is not None else "not_configured"
        response.warnings = []
        response.errors = []
        return response


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DistributedSafetyNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
