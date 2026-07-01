# Final Three-Pi Architecture

**Date:** 2026-07-01
**Status:** design frozen for implementation (Phases 3-14 build to this
document). Supersedes the single-Pi "monolithic vs. modular-Pi" model in
`docs/BOOT_TOPOLOGY.md` for physical multi-machine deployments; that
document's two modes remain valid for dev/lab/simulation use where a single
Pi (or a dev PC) is sufficient.

## Why three Pis, and why this split

The prior architecture (`docs/ARCHITECTURE_FREEZE.md`) already established
the correct *logical* separation of concerns — safety supervisor as sole
motion authority, LLM/dashboard forbidden from actuation, a single
behavior-decision pipeline. The three-Pi split turns that logical separation
into a **physical** one, for reasons the logical-only version can't provide:

- **Compute isolation.** A local LLM (Qwen2.5 0.5B) plus vision/audio
  perception is CPU/NPU-heavy; navigation/motor control needs
  low, predictable latency. Co-locating them risks the LLM starving the
  safety loop of CPU exactly when both are busy (a person approaching
  while the LLM is mid-inference). Physical separation removes that
  contention entirely.
- **Blast-radius isolation.** A camera driver crash, an Ollama OOM, or a
  dashboard bug can no longer take down the process that owns the e-stop
  and motor authority, because they are not the same machine.
- **Independent field maintenance.** Pi-1's touchscreen/dashboard can be
  swapped, rebooted, or reflashed without interrupting navigation; Pi-2's
  AI HAT can be debugged without disabling the ability to e-stop the robot.

## The three roles

| Pi | Role | Static IP | Owns | Never does |
|---|---|---|---|---|
| **Pi-1** | System UI/API | 192.168.10.11 | Dashboard, web API, system monitoring, deployment readiness, logs/alerts | Perception, LLM, navigation, actuation |
| **Pi-2** | Human AI | 192.168.10.12 | ASR/VAD, local LLM+RAG, face recognition, multi-person tracking, object/gesture/emotion AI, human state fusion, TTS | Direct motor/servo/navigation commands |
| **Pi-3** | Navigation/Motion/Safety | 192.168.10.13 | LiDAR, drive motors, steppers, servos, Nav2, Safety Supervisor, e-stop | Accepting unvalidated commands from Pi-1/Pi-2 |

## The authority principle (restated from Phase 3, summarized here for context)

**Pi-3 is the only physical-motion authority in the fleet.** Every other Pi
can only *propose*. This was already true logically on a single machine
(`bonbon_behavior_engine` is the sole constructor of `BehaviorDecision`,
`CommandAuthorizer.authorize()` gates against live `SafetyState`) — the
three-Pi architecture extends the same shape across a network boundary
instead of a function call boundary. See
`docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md` for the exact messages and
`docs/INTER_PI_COMMUNICATION_POLICY.md` for the transport-level rules.

```
Pi-1 (operator)  ──/bonbon/operator/proposal──┐
                                                ├──▶ Pi-3 Safety Supervisor ──▶ Pi-3 actuators
Pi-2 (LLM/AI)    ──/bonbon/behavior/proposal──┘        (sole approver)
```

Neither Pi-1 nor Pi-2 has a code path to any motor, servo, or navigation-
goal topic. This is enforced today on a single machine (verified in Phase 1
audit: `safety_gate_node.py` is the sole publisher of the final motion
topics) and must remain enforced identically once nodes run on separate
machines — the network boundary changes *how* a proposal physically travels,
not *who* is allowed to approve it.

## Runtime profiles

Each Pi boots from its own scoped profile — not a filtered view of one big
config, but a genuinely separate file, so a Pi can never accidentally load
a module it has no business running:

- `config/distributed/pi_ui_api.yaml`
- `config/distributed/pi_human_ai.yaml`
- `config/distributed/pi_navigation_safety.yaml`

Cross-cutting network/timing/failure config lives in:

- `config/distributed/robot_network.yaml` — static IPs, `ROS_DOMAIN_ID`,
  DDS discovery mode, chrony time sync, heartbeat timing.
- `config/distributed/topic_contracts.yaml` — every inter-Pi topic, its
  message type, publisher, and subscriber(s).
- `config/distributed/failure_policy.yaml` — exact behavior for every
  Pi-loses-Pi combination.

## Communication substrate

ROS2 over wired Ethernet only (no Wi-Fi for inter-Pi traffic — see
`robot_network.yaml`'s rationale). All three Pis share one `ROS_DOMAIN_ID`
so the existing ROS2 pub/sub graph — which the Phase 1 audit confirmed is
already correctly shaped (right nodes publish the right things, no
forbidden cross-role imports) — works across the network with **no changes
to node-internal logic**, only to *deployment*: per-Pi launch files
(Phase 2), DDS discovery config, and the new inter-Pi topics for proposals/
approvals/heartbeats (Phase 3).

## What's new vs. what's reused

**Reused as-is (Phase 1 audit confirmed these are already correctly built):**
Nav2, the safety supervisor singleton + its systemd `Conflicts=` guard, the
Dynamixel servo driver, the RPLiDAR driver, ASR/VAD/TTS/RAG/Ollama, human
state fusion, multi-person tracking, and — critically — the existing
`bonbon_msgs/BehaviorProposal` and `bonbon_msgs/BehaviorDecision` message
types, whose fields (`source_module` already includes `'operator'`,
`decision` already has `'approved'/'rejected'/'modified'/'deferred'/
'escalated'`) map almost exactly onto what the 3-Pi proposal/approval flow
needs. See `docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md` for how these are
extended (not replaced) for cross-Pi use.

**Genuinely new (net-new development, no prior version exists):**
`bonbon_motor_cytron_mdds30` + `bonbon_base_controller` (Phase 1 audit's
single most severe finding — the base cannot drive today, on any topology),
`bonbon_stepper_controller`, `bonbon_oakd_vision` (OAK-D Lite has no driver
today), `bonbon_distributed_safety` / `bonbon_authority_manager` /
`bonbon_motion_approval_gateway` (Phase 3), `bonbon_distributed_monitor` /
`bonbon_distributed_network_monitor` (Phases 4/7), `bonbon_fault_manager`
(Phase 11), and every per-Pi launch file and systemd unit (Phase 2/8).

## Deployment modes going forward

| Mode | When to use | Pi count |
|---|---|---|
| `monolithic` | dev laptop / CI / single-machine simulation | 1 (or 0 physical Pis) |
| `modular_pi` | single-Pi field test, all subsystems on one board | 1 |
| `three_pi` | production field deployment | 3 |

All three remain first-class, honestly-reported modes — `three_pi` is not a
replacement that deprecates the other two; see
`docs/BOOT_TOPOLOGY.md` (unchanged) for the first two, and the rest of this
document set for `three_pi`.
