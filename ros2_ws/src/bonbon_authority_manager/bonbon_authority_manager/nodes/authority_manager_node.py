"""AuthorityManagerNode — applies config/distributed/failure_policy.yaml
on this Pi, using its own HeartbeatMonitor view of peer liveness.

Runs on all three Pis (self_role param differs per pi_*.yaml runtime
profile) as an independent process from distributed_safety_node — both
subscribe the same /bonbon/pi{N}/heartbeat topics and run their own
HeartbeatMonitor instance rather than sharing in-process state, since ROS2
nodes are separate processes. This is intentional duplication of a cheap
computation (classify 2 peers' staleness), not a duplicate PIPELINE — no
sensor/actuator device is opened twice.

Publishes:
    /bonbon/system/degraded_mode   (bonbon_msgs/DegradedModeStatus) — Pi-3 only,
                                    per topic_contracts.yaml's authoritative-publisher assignment
    /bonbon/{self_id}/authority_status  (std_msgs/String, JSON) — Pi-1/Pi-2,
                                    informational dashboard/monitor feed only,
                                    never part of the proposal/approval chain
                                    (see INTER_PI_COMMUNICATION_POLICY.md Rule 1)

NOTE: imports rclpy/bonbon_msgs, not importable/testable in this dev
sandbox — syntax-checked via py_compile only. All decision logic lives in
core/authority_manager.py (9 unit tests, fully verified here).
"""

from __future__ import annotations

import json
import time

import rclpy
from bonbon_distributed_safety.core.heartbeat_monitor import HeartbeatConfig, HeartbeatMonitor, PiId
from bonbon_msgs.msg import DegradedModeStatus, ModuleHealth
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from bonbon_authority_manager.core.authority_manager import AuthorityManager, SelfRole

_ALL_ROLES = {
    "pi1": SelfRole.PI1_UI_API,
    "pi2": SelfRole.PI2_HUMAN_AI,
    "pi3": SelfRole.PI3_NAVIGATION_SAFETY,
}
_ALL_PI_IDS = {"pi1": PiId.PI1, "pi2": PiId.PI2, "pi3": PiId.PI3}

_QOS_HEARTBEAT = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class AuthorityManagerNode(LifecycleNode):
    def __init__(self, node_name: str = "authority_manager_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("self_id", "pi3")
        self.declare_parameter("stale_after_sec", 1.5)
        self.declare_parameter("lost_after_sec", 5.0)
        self.declare_parameter("evaluate_rate_hz", 2.0)

        self._self_id_str = "pi3"
        self._monitor: HeartbeatMonitor | None = None
        self._authority: AuthorityManager | None = None
        self._degraded_since: float | None = None
        self._pub_degraded_mode: LifecyclePublisher | None = None
        self._pub_authority_status: LifecyclePublisher | None = None
        self._timer = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        gp = self.get_parameter
        self._self_id_str = gp("self_id").get_parameter_value().string_value or "pi3"
        self_id = _ALL_PI_IDS.get(self._self_id_str, PiId.PI3)
        cfg = HeartbeatConfig(
            stale_after_sec=float(gp("stale_after_sec").get_parameter_value().double_value),
            lost_after_sec=float(gp("lost_after_sec").get_parameter_value().double_value),
        )
        self._monitor = HeartbeatMonitor(self_id, config=cfg)
        self._authority = AuthorityManager(
            _ALL_ROLES.get(self._self_id_str, SelfRole.PI3_NAVIGATION_SAFETY)
        )

        for peer in self._monitor.peers:
            self.create_subscription(
                ModuleHealth,
                f"/bonbon/{peer.value}/heartbeat",
                self._make_heartbeat_cb(peer),
                _QOS_HEARTBEAT,
            )

        if self._self_id_str == "pi3":
            self._pub_degraded_mode = self.create_lifecycle_publisher(
                DegradedModeStatus, "/bonbon/system/degraded_mode", _QOS_TRANSIENT
            )
        else:
            self._pub_authority_status = self.create_lifecycle_publisher(
                String, f"/bonbon/{self._self_id_str}/authority_status", _QOS_TRANSIENT
            )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        rate = float(self.get_parameter("evaluate_rate_hz").get_parameter_value().double_value)
        self._timer = self.create_timer(1.0 / rate, self._cb_evaluate)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._timer is not None:
            self._timer.cancel()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._monitor = None
        self._authority = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _make_heartbeat_cb(self, peer: PiId):
        def _cb(msg: ModuleHealth) -> None:
            if self._monitor is not None:
                self._monitor.on_heartbeat(peer, now=time.monotonic())

        return _cb

    def _cb_evaluate(self) -> None:
        if self._monitor is None or self._authority is None:
            return
        now = time.monotonic()
        link_states = self._monitor.snapshot(now)
        snap = self._authority.evaluate(link_states)

        is_degraded = bool(snap.degraded_modules)
        if is_degraded and self._degraded_since is None:
            self._degraded_since = now
        elif not is_degraded:
            self._degraded_since = None
        duration = (now - self._degraded_since) if self._degraded_since is not None else 0.0

        if self._pub_degraded_mode is not None:
            msg = DegradedModeStatus()
            msg.is_degraded = is_degraded
            msg.reason = snap.policy_reason
            msg.duration_sec = float(duration)
            self._pub_degraded_mode.publish(msg)
        if self._pub_authority_status is not None:
            payload = {
                "self_role": snap.self_role.value,
                "motion_authority_available": snap.motion_authority_available,
                "human_interaction_permitted": snap.human_interaction_permitted,
                "should_pause_proposals": snap.should_pause_proposals,
                "degraded_modules": list(snap.degraded_modules),
                "dashboard_message": snap.dashboard_message,
                "policy_reason": snap.policy_reason,
            }
            self._pub_authority_status.publish(String(data=json.dumps(payload)))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = AuthorityManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
