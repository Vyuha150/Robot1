"""MotionApprovalGatewayNode — Pi-3-only node, the sole subscriber of
/bonbon/behavior/proposal (Pi-2) and /bonbon/operator/proposal (Pi-1), and
the sole publisher of /bonbon/safety/approval, /bonbon/safety/rejection,
and /bonbon/motion/approved_command.

Every proposal is evaluated against the MOST RECENT bonbon_msgs/SafetyState
sample from bonbon_safety's safety_supervisor_node — this node makes no
independent safety determination; core/approval_gateway.py only translates
already-computed SafetyState capability flags into a per-proposal decision.
If no SafetyState has been received yet, every proposal is rejected (fail
closed, matching this repo's established safety posture — never assume
permissive defaults before the real safety state is known).

NOTE: imports rclpy/bonbon_msgs, not importable/testable in this dev
sandbox — syntax-checked via py_compile only. All decision logic lives in
core/approval_gateway.py (15 unit tests, fully verified here).
"""

from __future__ import annotations

import math
import uuid

import rclpy
from bonbon_msgs.msg import BehaviorDecision, BehaviorProposal, SafetyState
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from bonbon_motion_approval_gateway.core.approval_gateway import (
    MotionApprovalGateway,
    ProposalInput,
    SafetyContext,
)

_STATE_NAMES = {
    SafetyState.INITIALIZING: "INITIALIZING",
    SafetyState.NORMAL: "NORMAL",
    SafetyState.CAUTION: "CAUTION",
    SafetyState.DANGER: "DANGER",
    SafetyState.DOCKING: "DOCKING",
    SafetyState.DEGRADED: "DEGRADED",
    SafetyState.FAULT: "FAULT",
    SafetyState.SAFE_STOP: "SAFE_STOP",
}

_QOS_RELIABLE = QoSProfile(
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


def _fail_closed_context() -> SafetyContext:
    """No SafetyState received yet — reject everything except (handled by
    the gateway's own known-type check) nothing bypasses this."""
    return SafetyContext(
        state_name="INITIALIZING",
        actuation_permitted=False,
        navigation_permitted=False,
        max_velocity_mps=0.0,
        requires_manual_reset=True,
    )


class MotionApprovalGatewayNode(LifecycleNode):
    def __init__(self, node_name: str = "motion_approval_gateway_node") -> None:
        super().__init__(node_name)

        self._gateway = MotionApprovalGateway(event_id_factory=lambda: str(uuid.uuid4()))
        self._latest_safety: SafetyContext = _fail_closed_context()

        self._sub_behavior_proposal = None
        self._sub_operator_proposal = None
        self._sub_safety_state = None
        self._pub_approval: LifecyclePublisher | None = None
        self._pub_rejection: LifecyclePublisher | None = None
        self._pub_approved_command: LifecyclePublisher | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self._sub_behavior_proposal = self.create_subscription(
            BehaviorProposal, "/bonbon/behavior/proposal", self._cb_proposal, _QOS_RELIABLE
        )
        self._sub_operator_proposal = self.create_subscription(
            BehaviorProposal, "/bonbon/operator/proposal", self._cb_proposal, _QOS_RELIABLE
        )
        self._sub_safety_state = self.create_subscription(
            SafetyState, "/bonbon/safety/state", self._cb_safety_state, _QOS_TRANSIENT
        )
        self._pub_approval = self.create_lifecycle_publisher(
            BehaviorDecision, "/bonbon/safety/approval", _QOS_RELIABLE
        )
        self._pub_rejection = self.create_lifecycle_publisher(
            BehaviorDecision, "/bonbon/safety/rejection", _QOS_RELIABLE
        )
        self._pub_approved_command = self.create_lifecycle_publisher(
            BehaviorDecision, "/bonbon/motion/approved_command", _QOS_TRANSIENT
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._latest_safety = _fail_closed_context()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _cb_safety_state(self, msg: SafetyState) -> None:
        self._latest_safety = SafetyContext(
            state_name=_STATE_NAMES.get(msg.state, "UNKNOWN"),
            actuation_permitted=bool(msg.actuation_permitted),
            navigation_permitted=bool(msg.navigation_permitted),
            max_velocity_mps=float(msg.max_velocity_mps),
            requires_manual_reset=bool(msg.requires_manual_reset),
        )

    def _cb_proposal(self, msg: BehaviorProposal) -> None:
        # Yaw from quaternion -- same conversion bonbon_navigation's own
        # nodes use elsewhere in this repo, kept local here rather than a
        # cross-package import (see resource_guard.py's docstring on why
        # this repo keeps that convention for domain-to-domain code).
        q = msg.nav_goal_pose.orientation
        nav_goal_yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))

        proposal = ProposalInput(
            event_id=msg.event_id,
            source_module=msg.source_module,
            person_id=msg.person_id,
            proposal_type=msg.proposal_type,
            proposal_content=msg.proposal_content,
            urgency=float(msg.urgency),
            justification=msg.justification,
            safety_check_required=bool(msg.safety_check_required),
            nav_goal_x=float(msg.nav_goal_pose.position.x),
            nav_goal_y=float(msg.nav_goal_pose.position.y),
            nav_goal_yaw=nav_goal_yaw,
            nav_goal_label=msg.nav_goal_label,
        )
        result = self._gateway.evaluate(proposal, self._latest_safety)

        decision = BehaviorDecision()
        decision.event_id = result.event_id
        decision.source_module = "bonbon_motion_approval_gateway"
        decision.person_id = proposal.person_id
        decision.decision = result.decision
        decision.proposal_event_id = result.proposal_event_id
        decision.approved_action = result.approved_action
        decision.approved_content = result.approved_content
        decision.safety_approved = result.safety_approved
        decision.rejection_reason = result.rejection_reason
        decision.modification_note = result.modification_note
        decision.confidence = result.confidence
        decision.operator_alerted = result.operator_alerted
        decision.logged = result.logged
        decision.nav_goal_label = result.nav_goal_label
        decision.nav_goal_pose.position.x = result.nav_goal_x
        decision.nav_goal_pose.position.y = result.nav_goal_y
        decision.nav_goal_pose.orientation.z = math.sin(result.nav_goal_yaw * 0.5)
        decision.nav_goal_pose.orientation.w = math.cos(result.nav_goal_yaw * 0.5)

        if result.decision == "approved" and self._pub_approval is not None:
            self._pub_approval.publish(decision)
            if self._pub_approved_command is not None:
                self._pub_approved_command.publish(decision)
        elif self._pub_rejection is not None:
            self._pub_rejection.publish(decision)
            if result.operator_alerted:
                self.get_logger().warning(
                    f"proposal {proposal.event_id} escalated: {result.rejection_reason}"
                )


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MotionApprovalGatewayNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
