# Inter-Pi Communication Policy

**Date:** 2026-07-01
**Scope:** the rules every Pi's ROS2 nodes must follow when communicating
across the network boundary. Companion to
`docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md` (the exact topics/types) and
`config/distributed/failure_policy.yaml` (what happens when a peer is lost).

## Rule 1 — typed messages only, never raw strings

Every inter-Pi topic uses a real `bonbon_msgs` message type. No inter-Pi
topic may be `std_msgs/String` carrying JSON, even though that pattern is
used elsewhere in this repo for **intra-Pi, non-safety-relevant** dashboard/
status topics (e.g. `/bonbon/gesture/status`, `/bonbon/objects/status` —
see `docs/PERCEPTION_AI_CURRENT_AUDIT.md` for why that pattern was chosen
there: it avoids new `.msg` types for informational-only topics). Inter-Pi
communication is different: it crosses a trust and safety boundary, so the
schema must be enforced by the type system, not by convention. This is
exactly why `bonbon_msgs/BehaviorProposal` and `bonbon_msgs/BehaviorDecision`
(which already exist and are already CMakeLists-registered — see
`DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md`) are reused rather than replaced
with something looser.

## Rule 2 — proposals flow toward Pi-3, approvals flow away from it

Pi-1 and Pi-2 only ever *publish* proposals and *subscribe* to safety/
motion/navigation status. Neither ever subscribes to anything that would
let it infer "the safety supervisor will probably approve this" and act
preemptively — a proposal is inert until Pi-3 says otherwise. This mirrors
the existing single-machine invariant (`CommandAuthorizer.authorize()` gates
every `BehaviorDecision`) at the network level.

## Rule 3 — every Pi publishes a heartbeat, unconditionally

`/bonbon/pi{1,2,3}/heartbeat` is published by every Pi regardless of what
else is failing locally — even a Pi in a degraded or fault state must keep
heartbeating so its peers can distinguish "Pi-2 is alive but its camera
died" from "Pi-2 is gone." The heartbeat publisher must be one of the first
things to start (see boot order in each `config/distributed/pi_*.yaml`) and
must not depend on any other local service being healthy.

## Rule 4 — heartbeat loss triggers the documented policy, not silence

A Pi that stops hearing a peer's heartbeat must not simply keep going as if
nothing changed. It must apply the exact policy in
`config/distributed/failure_policy.yaml` for that specific pair
(`pi3_loses_pi1`, `pi3_loses_pi2`, `pi1_loses_pi3`, `pi2_loses_pi3`) and
surface the change via `/bonbon/system/failure_events` and the dashboard.
Silence is the one behavior this policy explicitly forbids.

## Rule 5 — no dashboard button bypasses the proposal path

Every actionable control on Pi-1's dashboard (move here, dock now, retract
arm, etc.) publishes to `/bonbon/operator/proposal` and nothing else. There
is no "emergency override" REST endpoint that reaches a motor topic
directly — if an operator needs to force a stop, that's the existing e-stop
path (hardware button, or a dedicated, safety-supervisor-owned
`/bonbon/safety/*` service), not a movement command that skips validation.

## Rule 6 — Pi-2's LLM output never becomes an inter-Pi command directly

An LLM response is text. Converting it into a `BehaviorProposal` happens
inside Pi-2's own behavior/intent pipeline (rule-engine → RAG → LLM
resolution order, per `config/distributed/pi_human_ai.yaml`), and even then
it's a proposal like any other `source_module` value — `'llm'` carries no
special trust weight in `CommandAuthorizer`/the safety supervisor's
evaluation. This was already true on one machine; it stays true across the
network.

## Rule 7 — network transport failures are distinguishable from validation rejections

A proposal that never reaches Pi-3 (network partition) and a proposal that
reaches Pi-3 and is explicitly rejected must produce **different** dashboard
states: the former shows "Pi-3 unreachable" (per `pi1_loses_pi3` policy),
the latter shows the actual `rejection_reason` field from the
`BehaviorDecision`. Conflating them would hide real safety rejections behind
a generic "offline" status, or worse, hide real network problems behind an
apparently-normal "rejected" status.

## Rule 8 — QoS must tolerate real network latency, not just loopback

Topics used for the proposal/approval/status chain use `RELIABLE` QoS
(matching the existing `SafetyState` QoS choice — `RELIABLE`/
`TRANSIENT_LOCAL`, so a late-joining or reconnecting Pi immediately gets the
last known state rather than waiting for the next publish cycle). Heartbeat
topics use `BEST_EFFORT` intentionally — a dropped heartbeat sample is
harmless (the next one arrives in `1/publish_rate_hz` seconds); forcing
`RELIABLE` retransmission on a heartbeat would waste bandwidth for no safety
benefit.

## Rule 9 — chrony time sync is a prerequisite, not an optimization

Because heartbeat staleness and cross-Pi event ordering are time-based
(`config/distributed/robot_network.yaml`'s `stale_after_sec`/
`lost_after_sec`), clock drift between Pis directly degrades failure
detection accuracy. `bonbon_distributed_network_monitor` (Phase 7) must
alert (not silently tolerate) when observed clock offset exceeds
`alert_offset_ms`.

## Rule 10 — this policy applies identically regardless of which Pi initiates

There is no special case where Pi-3 trusts a message more because it came
from a particular source IP instead of because of the message's own
`source_module`/`decision` fields. Trust is expressed in the typed message
content and validated in code, never inferred from network topology alone
(a compromised or misconfigured Pi-1/Pi-2 must not gain authority just by
being on the expected IP).
