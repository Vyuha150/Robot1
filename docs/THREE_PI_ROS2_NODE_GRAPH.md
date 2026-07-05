# Three-Pi ROS2 Node Graph

**Date:** 2026-07-01 (BOM-accuracy corrections 2026-07-06 — see rows
marked "(2026-07-06)"; several nodes below were marked **MISSING**/**NEW**
against a package name that was never actually used once implemented, e.g.
`bonbon_distributed_monitor` → the real packages are `bonbon_distributed_
safety` + `bonbon_authority_manager`. Corrected against the real code.)
**Scope:** every ROS2 node in the target deployment, which Pi it runs on,
and its cross-Pi edges. Existing nodes are cited with their current
file:line; new nodes (not yet implemented) are marked **NEW**.

## Pi-1 (192.168.10.11) — `pi_ui_api`

| Node | Package | Status | Cross-Pi subscriptions | Cross-Pi publications |
|---|---|---|---|---|
| `operator_api_node` | `bonbon_operator_api` / `bonbon_dashboard_api` | Existing (`main.py`) | `/bonbon/safety/state`, `/bonbon/motion/status`, `/bonbon/safety/approval`, `/bonbon/safety/rejection`, `/bonbon/human_state/active`, `/bonbon/pi2/heartbeat`, `/bonbon/pi3/heartbeat` | `/bonbon/operator/proposal` |
| `distributed_safety_node` + `authority_manager_node` | `bonbon_distributed_safety` + `bonbon_authority_manager` | Existing — corrected (2026-07-06) from this row's original placeholder package name `bonbon_distributed_monitor`, which was never actually built | `/bonbon/pi{1,2,3}/heartbeat` | `/bonbon/{self_id}/authority_status` (informational only, outside the approval chain) |
| `fault_manager_node` | `bonbon_fault_manager` | **NEW** (2026-07-06) | `/bonbon/hal/fault`, `/bonbon/safety/state` (network-wide via shared DDS domain, no bridging) | `/bonbon/fault_manager/registry` |
| `bonbon_ui_api_bringup` | `bonbon_ui_api_bringup` | **NEW** (2026-07-06) | n/a — composition-only launch package (no bonbon_hal include; Pi-1 owns no BOM hardware) | n/a |

Frontend (React/Vite, `bonbon_operator_api/frontend`) is not a ROS2 node —
it talks to `operator_api_node` over REST/WebSocket only. The touchscreen
kiosk browser (`devops/scripts/launch_kiosk.sh`, 2026-07-06) is likewise not
a ROS2 node — it's a systemd-invoked shell process pointed at the frontend.

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
| `actuation_node` | `bonbon_actuation` | Existing — joint topology corrected (2026-07-06): single right arm (shoulder/elbow/wrist) + 2-DOF head (pan/tilt), not a symmetric two-arm robot; 3 field-name bugs found and fixed (dead HAL topic, wrong `ServoState`/`SafetyState`/`ActuationStatus` field names — gestures previously never reached hardware) | (local `SafetyState` only) | none directly (publishes to `bonbon_safety`'s raw topics, never bypasses the gate) |
| `estop_node` | `bonbon_safety` | Existing | none | (local only, feeds `SafetyState`) |
| `lidar_node` | `bonbon_hal` / `bonbon_lidar_rplidar` | Existing | none | none (intra-Pi only) |
| `servo_node` | `bonbon_hal` / `bonbon_servo_controller` | Existing — corrected (2026-07-06): primary backend is `PCA9685ServoDriver` (real BOM hardware, 16-channel I2C PWM), not Dynamixel; `DynamixelDriver` kept as a selectable, non-primary backend | none | `/bonbon/servo/{neck,arm}/state` (dashboard-visible via `bonbon_fault_manager`, 2026-07-06) |
| `stepper_node` | `bonbon_hal` | **NEW** (2026-07-06) — real BOM hardware (2x NEMA17 closed-loop, HEAD pan + RIGHT ARM shoulder), corrected from this row's original **MISSING** entry (see gap report item 2, resolved) | none | `/bonbon/stepper/command` (gated through `safety_gate_node`) |
| `base_controller_node` | `bonbon_base_controller` | Existing — corrected (2026-07-06) from **MISSING**, see gap report item 1 (resolved) | none | publishes `nav_msgs/Odometry` |
| `motor_node` | `bonbon_hal` (`CytronMDDS30Driver`) | Existing — corrected (2026-07-06) from this row's original placeholder package name `bonbon_motor_cytron_mdds30`/**MISSING**, see gap report item 1 (resolved) | none | none (intra-Pi only, feeds `base_controller_node`) |
| `navigation_node` | `bonbon_navigation` / `bonbon_navigation_bringup` | Existing (real Nav2) | (local `SafetyState` only) | `/bonbon/navigation/status`, `/bonbon/motion/status` |
| `navigation_monitor_node` | `bonbon_navigation_monitor` | **NEW** (Phase 6) | none | contributes to `/bonbon/system/component_health` |
| `distributed_safety_node` + `authority_manager_node` | `bonbon_distributed_safety` + `bonbon_authority_manager` | Existing (self_id=pi3) | `/bonbon/pi{1,2}/heartbeat` | `/bonbon/pi3/heartbeat`, `/bonbon/system/degraded_mode` (Pi-3 is the authoritative publisher per `topic_contracts.yaml`) |
| `bonbon_navigation_bringup` | `bonbon_navigation_bringup` | **NEW** (2026-07-06) | n/a — composition-only launch package (lidar/motor/servo/stepper/estop/imu/battery ONLY; camera/mic/speaker explicitly excluded; `bonbon_safety` launched FIRST) | n/a |

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
Pi-2 ──/bonbon/hal/fault──────────────────────▶ Pi-1 (bonbon_fault_manager, 2026-07-06)
Pi-3 ──/bonbon/hal/fault──────────────────────▶ Pi-1 (bonbon_fault_manager, 2026-07-06)
Pi-3 ──/bonbon/safety/state───────────────────▶ Pi-1 (bonbon_fault_manager, 2026-07-06 — in
                                                 addition to the existing Pi-1 dashboard consumer)
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
