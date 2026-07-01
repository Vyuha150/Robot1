# bonbon_motion_approval_gateway

Pi-3-only. The sole subscriber of `/bonbon/behavior/proposal` (from Pi-2)
and `/bonbon/operator/proposal` (from Pi-1), and the sole publisher of
`/bonbon/safety/approval`, `/bonbon/safety/rejection`, and
`/bonbon/motion/approved_command`. This is the network-boundary extension
of the authority chain the single-machine architecture already enforced
(`CommandAuthorizer.authorize()` gating against live `SafetyState`) — see
`docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md` for the full rationale,
including why the existing (previously unused) `bonbon_msgs/BehaviorProposal`
and `bonbon_msgs/BehaviorDecision` types are reused here rather than new
ones invented.

## Fail-closed by design

Every proposal is evaluated against the most recently received
`bonbon_msgs/SafetyState`. If none has been received yet (node just
started), every proposal is rejected — there is no permissive default
"assume safe until told otherwise." See `_fail_closed_context()` in
`nodes/motion_approval_gateway_node.py`.

## What it does NOT do

It does not compute `SafetyState` itself (that's `bonbon_safety`'s
`safety_supervisor_node`, unchanged by this package) and it does not
publish the actual motor `Twist` (`/cmd_vel` stays local to Pi-3, produced
by the existing `safety_gate_node` — see
`docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md`'s explanation of why a raw
velocity command never needs to leave the machine that owns the motors).

## Core logic (fully unit-tested, no rclpy dependency)

`core/approval_gateway.py` — `MotionApprovalGateway.evaluate()`. Every test
name states the safety property it protects (e.g.
`test_operator_source_gets_no_special_bypass_in_danger`,
`test_unknown_proposal_type_never_silently_approved`). Stateless per call —
no proposal history influences a later, differently-risky proposal's
outcome. 15 tests in `tests/test_approval_gateway.py`.
