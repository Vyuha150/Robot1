# Three-Pi ROS2 Node Graph

**Date:** 2026-07-01
**Scope:** every ROS2 node in the target deployment, which Pi it runs on,
and its cross-Pi edges. Existing nodes are cited with their current
file:line; new nodes (not yet implemented) are marked **NEW**.

## Pi-1 (192.168.10.11) — `pi_ui_api`

| Node | Package | Status | Cross-Pi subscriptions | Cross-Pi publications |
|---|---|---|---|---|
| `operator_api_node` | `bonbon_operator_api` / `bonbon_dashboard_api` | Existing (`main.py`) | `/bonbon/safety/state`, `/bonbon/motion/status`, `/bonbon/safety/approval`, `/bonbon/safety/rejection`, `/bonbon/human_state/active`, `/bonbon/pi2/heartbeat`, `/bonbon/pi3/heartbeat` | `/bonbon/operator/proposal` |
| `distributed_monitor_node` | `bonbon_distributed_monitor` | **NEW** (Phase 4) | `/bonbon/pi{1,2,3}/heartbeat`, `/bonbon/system/component_health`, `/bonbon/system/failure_events` | `/bonbon/system/distributed_status` |

Frontend (React/Vite, `bonbon_operator_api/frontend`) is not a ROS2 node —
it talks to `operator_api_node` over REST/WebSocket only.

## Pi-2 (192.168.10.12) — `pi_human_ai`

| Node | Package | Status | Cross-Pi subscriptions | Cross-Pi publications |
|---|---|---|---|---|
| `camera_node` (OAK-D backend) | `bonbon_hal` / `bonbon_oakd_vision` | Driver gap — see gap report item 3 | none | none (intra-Pi only) |
| `microphone_node` (ReSpeaker) | `bonbon_hal` / `bonbon_respeaker_audio` | Existing | none | none (intra-Pi only) |
| `speech_node` (ASR+VAD) | `bonbon_speech` / `bonbon_asr` | Existing | none | none (intra-Pi only) |
| `vision_node` (incl. face recognition) | `bonbon_vision` / `bonbon_face_recognition` | Existing | `/bonbon/safety/state` | none (intra-Pi only) |
| `multi_person_tracker_node` | `bonbon_multi_person_tracker` | Existing (53/53 tests) | `/bonbon/safety/state` | none (intra-Pi only) |
| `object_intelligence_node` | `bonbon_object_intelligence` | Existing, improved this session | `/bonbon/safety/state` | none (intra-Pi only) |
| `gesture_node` | `bonbon_gesture` / `bonbon_gesture_intelligence` | Existing (94 tests) | `/bonbon/safety/state` | none (intra-Pi only) |
| `affective_ai_node` | `bonbon_affective_ai` | Existing | `/bonbon/safety/state` | none (intra-Pi only) |
| `human_state_fusion_node` | `bonbon_human_state_fusion` | Existing (73/73 tests) | `/bonbon/safety/state` | `/bonbon/human_state/active` |
| `llm_orchestrator_node` | `bonbon_llm` / `bonbon_local_llm_gateway` | Existing, needs `qwen2.5:0.5b` config | `/bonbon/safety/state` | none directly (feeds behavior_engine_node) |
| `behavior_engine_node` | `bonbon_behavior_engine` | Existing — role narrows to proposal-construction only in 3-Pi split | `/bonbon/safety/state` | **`/bonbon/behavior/proposal`** |
| `speaker_intelligence_node` | `bonbon_speaker_intelligence` | Existing (43 tests) | `/bonbon/safety/state` | none (intra-Pi only) |
| `tts_node` | `bonbon_tts` | Existing | none | none (intra-Pi only) |

**Important architecture note:** `behavior_engine_node` currently
constructs *both* `BehaviorProposal` and `BehaviorDecision` locally
(confirmed by audit — it publishes `/bonbon/behavior/decision` today with
zero subscribers). In the 3-Pi split, its `BehaviorDecision`-publishing
responsibility is **superseded**, not duplicated, by Pi-3's new
`bonbon_motion_approval_gateway` — `behavior_engine_node` on Pi-2 should be
reconfigured (Phase 3 implementation task, not yet done) to publish only
proposals and stop constructing decisions itself, so there is exactly one
decision-maker in the fleet, matching the existing single-supervisor
principle applied to this new topic pair.

## Pi-3 (192.168.10.13) — `pi_navigation_safety`

| Node | Package | Status | Cross-Pi subscriptions | Cross-Pi publications |
|---|---|---|---|---|
| `safety_supervisor_node` | `bonbon_safety` / `bonbon_safety_supervisor` | Existing (singleton, verified) | `/bonbon/human_state/active` (advisory only) | **`/bonbon/safety/state`** |
| `safety_gate_node` | `bonbon_safety` / `bonbon_motion_safety` | Existing | (local `SafetyState` only) | none directly (feeds local `/cmd_vel`) |
| `motion_approval_gateway_node` | `bonbon_motion_approval_gateway` | **NEW** (Phase 3) | `/bonbon/behavior/proposal`, `/bonbon/operator/proposal` | `/bonbon/safety/approval`, `/bonbon/safety/rejection`, `/bonbon/motion/approved_command` |
| `estop_node` | `bonbon_safety` | Existing | none | (local only, feeds `SafetyState`) |
| `lidar_node` | `bonbon_hal` / `bonbon_lidar_rplidar` | Existing | none | none (intra-Pi only) |
| `servo_node` | `bonbon_hal` / `bonbon_servo_controller` | Existing (Dynamixel) | none | `/bonbon/servo/{neck,arm}/state` (dashboard-visible, Phase 8) |
| `base_controller_node` | `bonbon_base_controller` | **MISSING** — see gap report item 1 | none | (would publish odometry) |
| `motor_cytron_node` | `bonbon_motor_cytron_mdds30` | **MISSING** — see gap report item 1 | none | none |
| `stepper_controller_node` | `bonbon_stepper_controller` | **MISSING** — see gap report item 2 | none | none |
| `navigation_node` | `bonbon_navigation` / `bonbon_navigation_bringup` | Existing (real Nav2) | (local `SafetyState` only) | `/bonbon/navigation/status`, `/bonbon/motion/status` |
| `navigation_monitor_node` | `bonbon_navigation_monitor` | **NEW** (Phase 6) | none | contributes to `/bonbon/system/component_health` |

## Full cross-Pi edge list (condensed)

```
Pi-1 ──/bonbon/operator/proposal──────────────▶ Pi-3
Pi-2 ──/bonbon/behavior/proposal──────────────▶ Pi-3
Pi-2 ──/bonbon/human_state/active─────────────▶ Pi-3, Pi-1
Pi-3 ──/bonbon/safety/state───────────────────▶ Pi-2 (8 subscribers), Pi-1
Pi-3 ──/bonbon/safety/approval────────────────▶ Pi-1, Pi-2
Pi-3 ──/bonbon/safety/rejection───────────────▶ Pi-1, Pi-2
Pi-3 ──/bonbon/motion/approved_command────────▶ Pi-1, Pi-2
Pi-3 ──/bonbon/motion/status──────────────────▶ Pi-1, Pi-2
Pi-1 ──/bonbon/pi1/heartbeat──────────────────▶ Pi-2, Pi-3
Pi-2 ──/bonbon/pi2/heartbeat──────────────────▶ Pi-1, Pi-3
Pi-3 ──/bonbon/pi3/heartbeat──────────────────▶ Pi-1, Pi-2
any  ──/bonbon/system/component_health────────▶ Pi-1
any  ──/bonbon/system/failure_events──────────▶ Pi-1
Pi-3 ──/bonbon/system/degraded_mode───────────▶ Pi-1, Pi-2
```

No edge points into Pi-3 that carries a motor/servo/navigation-goal command
directly — every arrow into Pi-3 is a proposal or a heartbeat; only Pi-3
publishes anything actuation-relevant, and it never leaves Pi-3 as a raw
command (see `DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md`'s explanation of why
`/cmd_vel` stays local to Pi-3).

## What does NOT change

Every node listed as "Existing" above keeps its current internal logic
unchanged by this graph — the only change for those nodes is that some of
their existing topic subscriptions/publications now traverse a network
link instead of loopback. No node's callback logic, message construction,
or safety-relevant decision code is modified by the 3-Pi split itself; that
work (where still needed, e.g. `behavior_engine_node`'s decision-publishing
role narrowing) is scoped to Phase 3 implementation, not this design
document.
