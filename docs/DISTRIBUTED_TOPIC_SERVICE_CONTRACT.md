# Distributed Topic/Service Contract

**Date:** 2026-07-01
**Scope:** the exact ROS2 interface every inter-Pi topic uses, why each type
was chosen, and how today's single-machine wiring maps onto the three-Pi
split. Machine-checked companion:
`config/distributed/topic_contracts.yaml`. Policy companion:
`docs/INTER_PI_COMMUNICATION_POLICY.md`.

## Key discovery this contract is built on

Auditing the current single-machine graph (read-only, no code changed)
found that `bonbon_msgs/msg/BehaviorProposal` and `bonbon_msgs/msg/
BehaviorDecision` **already exist, are already registered in
`bonbon_msgs/CMakeLists.txt`, and are already published** by
`behavior_engine_node` on `/bonbon/behavior/proposal` and `/bonbon/behavior/
decision` — but **have zero subscribers anywhere in the repo today**. Their
fields already anticipate almost everything the 3-Pi authority model needs:

- `BehaviorProposal.source_module` already accepts `'llm'`, `'speech_intent'`,
  `'gesture'`, `'rule_engine'`, **and `'operator'`** — the exact distinction
  Phase 3 needs between AI-originated and operator-originated proposals.
- `BehaviorDecision.decision` already has `'approved'`, `'rejected'`,
  `'modified'`, `'deferred'`, `'escalated'` — the exact vocabulary the
  brief's `/bonbon/safety/approval` and `/bonbon/safety/rejection` topics
  need, split by decision value rather than requiring two message types.
- `BehaviorDecision.rejection_reason`, `.safety_approved`, `.operator_alerted`,
  `.logged` already give the dashboard everything it needs to explain *why*
  something was rejected, not just that it was.

This means the 3-Pi proposal/approval flow can be built by **giving these
existing, unused topics their first real subscriber on the correct Pi**,
rather than inventing a parallel set of new message types — which matters
because this dev environment cannot build/verify new `.msg` files (no
working `colcon build`), so minimizing new interface surface area directly
reduces deployment risk. See `docs/PERCEPTION_AI_CURRENT_AUDIT.md`'s
`bonbon_vision_test_hang` finding for why that risk is real in this repo,
not hypothetical.

## Full inter-Pi interface table

See `config/distributed/topic_contracts.yaml` for the machine-checked
version (exact QoS, publisher/subscriber Pi assignment). Summary:

| Topic | Type | Publisher | Subscribers | New or reused? |
|---|---|---|---|---|
| `/bonbon/behavior/proposal` | `BehaviorProposal` | Pi-2 | Pi-3 | Reused (first real subscriber) |
| `/bonbon/operator/proposal` | `BehaviorProposal` | Pi-1 | Pi-3 | Reused type, new topic name |
| `/bonbon/safety/approval` | `BehaviorDecision` | Pi-3 | Pi-1, Pi-2 | Reused type, new topic name |
| `/bonbon/safety/rejection` | `BehaviorDecision` | Pi-3 | Pi-1, Pi-2 | Reused type, new topic name |
| `/bonbon/motion/approved_command` | `BehaviorDecision` | Pi-3 | Pi-1, Pi-2 | Reused type, new topic name (telemetry, not actuation) |
| `/bonbon/motion/status` | `NavigationStatus` | Pi-3 | Pi-1, Pi-2 | Reused |
| `/bonbon/safety/state` | `SafetyState` | Pi-3 | Pi-1, Pi-2 | Reused as-is, now crosses network |
| `/bonbon/human_state/active` | `HumanState` | Pi-2 | Pi-3, Pi-1 | Reused as-is |
| `/bonbon/pi{1,2,3}/heartbeat` | `ModuleHealth` | each Pi | other two | Reused type for a new purpose |
| `/bonbon/system/distributed_status` | `std_msgs/String` (JSON) | Pi-1 | dashboard WS only | New, informational-only (see exception scope below) |
| `/bonbon/system/component_health` | `ModuleHealth` | any | Pi-1 | Reused |
| `/bonbon/system/failure_events` | `SafetyEvent` | any | Pi-1 | Reused |
| `/bonbon/system/degraded_mode` | `DegradedModeStatus` | Pi-3 | Pi-1, Pi-2 | Reused |

## Why `/cmd_vel` (the actual motor Twist) does NOT cross the network

The Phase 1 audit traced the current motion-authority chain precisely:
`safety_gate_node.py` is the sole publisher of `/cmd_vel`
(`geometry_msgs/Twist`, `BEST_EFFORT`/depth=1), and it is the *only* node
between it and the physical Cytron/servo drivers. In the 3-Pi split, both
the safety gate and every actuator it drives live on Pi-3. There is no
reason for a raw `Twist` to ever leave Pi-3 — doing so would only add
network latency to the highest-frequency, most safety-sensitive control
loop in the system for no benefit. `/bonbon/motion/approved_command`
exists instead as a lower-frequency, `TRANSIENT_LOCAL` **telemetry** view
of what's currently approved, for the dashboard and Pi-2's own advisory
use — never as the actuation path itself.

## Why `/bonbon/safety/state` crossing the network is the biggest wiring change

Of `SafetyState`'s 14 confirmed local subscribers today, **8 move to Pi-2**
in the 3-Pi split: `affective_ai_node`, `gesture_node`,
`human_state_fusion_node`, `llm_orchestrator_node`,
`multi_person_tracker_node`, `object_intelligence_node`,
`speaker_intelligence_node`, and (per Phase 1 finding) whichever node hosts
`bonbon_perception_efficiency`. This is not a change to those nodes' logic —
they already correctly subscribe to `/bonbon/safety/state` and react to it
— it is purely a networking concern: the topic must now traverse Ethernet
+ shared `ROS_DOMAIN_ID` instead of loopback. This is exactly Blocker 1 and
Blocker 3 in `docs/DISTRIBUTED_DEPLOYMENT_BLOCKERS.md`, and is the
single most safety-relevant piece of Phase 7's network validation.

## The `CommandAuthorizer` pre-filter stays on Pi-2, advisory-only

`bonbon_llm/safety/authorization.py`'s `CommandAuthorizer.authorize()` is
used by `llm_orchestrator_node` to pre-filter which behavior classes it
even bothers proposing, based on a locally-cached `SafetySnapshot` derived
from `/bonbon/safety/state`. This is **preserved as-is** in the 3-Pi
design: it only ever influences what Pi-2 *proposes*, never what gets
*executed* — final actuation still requires Pi-3's explicit `BehaviorDecision`
via `/bonbon/safety/approval`. This is not a second authority; it's an
efficiency optimization (don't bother sending a proposal you already know
will be rejected) that must never be mistaken for validation. Documented
here explicitly so Phase 3 implementation does not accidentally treat
Pi-2's `CommandAuthorizer` result as sufficient to skip Pi-3's gate.

## Services

No cross-Pi ROS2 *services* (request/response) are introduced by this
contract — all inter-Pi communication is topic-based pub/sub. This is
deliberate: services block the calling node until a response arrives,
which is a poor fit across a network link that can legitimately be slow or
partitioned (see `failure_policy.yaml`). Existing local services
(`NavigateTo.srv`, `CancelNavigation.srv`, etc.) remain intra-Pi-3 or
intra-Pi-1-to-Pi-3-via-proposal, not raw cross-Pi service calls.

## What Phase 3 must still build (not yet done — this is a Phase 2 design doc)

- `bonbon_motion_approval_gateway` node on Pi-3: subscribes
  `/bonbon/behavior/proposal` + `/bonbon/operator/proposal`, is the first
  real consumer either topic has ever had, and is the sole publisher of
  `/bonbon/safety/approval` / `/bonbon/safety/rejection` /
  `/bonbon/motion/approved_command`.
- `bonbon_distributed_safety` / `bonbon_authority_manager` packages per the
  brief's Phase 3 naming.
- Heartbeat publishers on all three Pis (`bonbon_distributed_monitor` on
  Pi-1, equivalents on Pi-2/Pi-3, or a shared small package used by all
  three — implementation choice for Phase 3/7).
