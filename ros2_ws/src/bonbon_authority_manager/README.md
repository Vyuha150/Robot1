# bonbon_authority_manager

Applies `config/distributed/failure_policy.yaml` on THIS Pi, using its own
`HeartbeatMonitor` view of peer liveness (reused from
`bonbon_distributed_safety.core`, run as an independent instance in this
node's own process — see the module docstring in
`nodes/authority_manager_node.py` for why that's intentional, cheap
duplication of computation, not a duplicate pipeline).

Each Pi runs its own instance scoped to its own role — there is no central
arbiter, matching `failure_policy.yaml`'s
`each_pi_applies_its_own_loss_policies_independently` rule
(`docs/FAILURE_AND_DEGRADED_MODE_POLICY.md`).

## What it publishes

- Pi-3: `/bonbon/system/degraded_mode` (`DegradedModeStatus`) — the
  authoritative source per `config/distributed/topic_contracts.yaml`.
- Pi-1 / Pi-2: `/bonbon/{self_id}/authority_status` (`std_msgs/String`,
  JSON) — informational dashboard/monitor feed only, explicitly outside
  the proposal/approval chain (`docs/INTER_PI_COMMUNICATION_POLICY.md`
  Rule 1's documented exception scope).

## Core logic (fully unit-tested, no rclpy dependency)

`core/authority_manager.py` — `AuthorityManager.evaluate()`. One test
class per `SelfRole` (Pi-1/Pi-2/Pi-3), verifying each Pi applies *only*
its own failure_policy.yaml scenario and never accidentally reacts to a
peer-loss combination that isn't its concern (e.g. Pi-3 losing Pi-1 must
never touch `human_interaction_permitted`). 9 tests in
`tests/test_authority_manager.py`.
