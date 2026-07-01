# Architecture Freeze — Release Candidate

**Date:** 2026-07-01
**Status:** FROZEN for this release candidate. Anything not listed here as
part of the release is **POST-RELEASE** — see [NEXT_RELEASE_ROADMAP.md](NEXT_RELEASE_ROADMAP.md).
This document is the single source of truth for "what ships"; if a future
change contradicts it, update this document in the same change, don't let
them drift apart.

## 1. Final package list (27 ROS2 packages)

| Package | Role |
|---|---|
| `bonbon_msgs`, `bonbon_srvs`, `bonbon_actions` | Interface definitions |
| `bonbon_hal` | Hardware abstraction (motors, sensors, battery) |
| `bonbon_safety` | Safety Supervisor, e-stop, safety policy engine |
| `bonbon_vision` | Camera capture + object/person detection (runtime-abstracted) |
| `bonbon_ai_runtime` | Hailo/CPU/TensorRT/Mock inference runtime abstraction |
| `bonbon_object_intelligence` | Object classification/tracking core |
| `bonbon_multi_person_tracker` | Multi-person identity tracking |
| `bonbon_gesture` | Gesture recognition (hand/body/head classifiers) |
| `bonbon_speech` | STT, VAD, mic capture |
| `bonbon_speaker_intelligence` | Speaker diarization, active-speaker assignment |
| `bonbon_affective_ai` | Voice/face emotion signals (uncertain-by-policy) |
| `bonbon_human_state_fusion` | Fuses perception signals into a human-state estimate |
| `bonbon_spatial` | Spatial/scene reasoning |
| `bonbon_behavior_engine` | The single behavior-decision layer |
| `bonbon_llm` | LLM orchestration, `CommandAuthorizer`, RAG, personality layer |
| `bonbon_actuation` | Gated actuator dispatch (`ActuationSafetyGate`) |
| `bonbon_navigation` | Nav2-based navigation |
| `bonbon_tts` | Speech synthesis (Piper) |
| `bonbon_perception_efficiency` | Load shedding, thermal/CPU policy, `PiEfficiencyProfile` |
| `bonbon_data_feedback` | Privacy-safe failure-case capture (live perception layer) |
| `bonbon_data_stores` | Shared SQLite connection/schema utilities |
| `bonbon_operator_api` | Dashboard backend (FastAPI) + frontend |
| `bonbon_bringup` | Monolithic launch (`bringup.launch.py`) |
| `bonbon_simulation` | Simulation harness for CI-safe scenario replay |
| `bonbon_perception_ai` | AI-layer perception glue used by monolithic bringup |
| `bonbon_perception` | **Quarantined** — superseded by `bonbon_vision` + `bonbon_gesture` + `bonbon_affective_ai`; launch disabled, kept for reference only |

Top-level, non-ROS2 packages that are part of this release:
`bonbon_behavior_validation/` (Behavior Oracle, production score),
`bonbon_field_learning/` (privacy-safe field failure → regression loop).

## 2. Final ROS2 node graph

```
                         ┌────────────────────┐
                         │   Safety Supervisor  │◄──── e-stop poll (50 Hz)
                         │   (bonbon_safety)     │
                         └──────────┬───────────┘
                     SafetyState (transient-local)
              ┌───────────────┼───────────────────────┐
              v               v                        v
     bonbon_navigation   bonbon_actuation      bonbon_operator_api
     (nav2, gated)     (ActuationSafetyGate)   (SafetyCommandGate)
              ^               ^
              │               │  ActuationGesture / BehaviorDecision
              │        ┌──────┴───────┐
              │        │ behavior_engine│◄── the ONLY node that constructs
              │        │    _node       │    BehaviorDecision/ActuationGesture
              │        └──────┬────────┘
              │               │ (advisory only, never direct)
              │        ┌──────┴───────┐
              │        │ llm_orchestrator│── CommandAuthorizer gates every
              │        │     _node       │   LLM-resolved behavior against
              │        └──────┬───────┘   live SafetyState before dispatch
              │               │
    ┌─────────┴───────────────┴─────────────────────────┐
    │        human_state_fusion  <  spatial              │
    │              ^      ^      ^                        │
    │        gesture  speaker_intelligence  affective_ai   │
    │              ^                  ^                    │
    │      multi_person_tracker    speech (STT/VAD)         │
    │              ^                                        │
    │      object_intelligence  <  bonbon_vision (ai_runtime)│
    │              ^                                        │
    │            bonbon_hal (camera/mic/motors/battery)      │
    └──────────────────────────────────────────────────────┘

    bonbon_tts  ← speak requests from behavior_engine / dashboard (gated)
    bonbon_perception_efficiency ← cross-cutting: shedding/thermal policy
    bonbon_data_feedback ← cross-cutting: anonymized failure capture
```

## 3. Final topic/service/action map (safety-relevant subset)

| Interface | Type | Publisher | Subscribers |
|---|---|---|---|
| `/bonbon/safety/state` | `SafetyState` (transient-local) | Safety Supervisor (exactly one) | navigation, actuation, dashboard bridge, behavior_engine, llm_orchestrator (read-only) |
| `/bonbon/behavior/decision` | `BehaviorDecision` | `behavior_engine_node` (only constructor) | actuation, dashboard |
| `/bonbon/actuation/gesture` | `ActuationGesture` | `behavior_engine_node` (only constructor) | `bonbon_actuation` (gated by `ActuationSafetyGate`) |
| `NavigateTo.srv`, `CancelNavigation.srv`, `GetNearestCharger.srv` | services | `bonbon_navigation` | dashboard, behavior_engine |
| `LLMQuery.srv` | service | defined, **not yet served** (see [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)) | dashboard (`rag_query` command) |
| `PerceptionEfficiencyMetrics` | msg | `bonbon_perception_efficiency` | dashboard performance card |
| `ResourceUsage` | msg | `bonbon_hal` | dashboard, `bonbon_safety` |

Full interface list: `bonbon_msgs`/`bonbon_srvs`/`bonbon_actions` package sources (frozen for this release; no new interfaces added by this finalization pass).

## 4. Final command flow

```
Operator/LLM intent
      v
CommandAuthorizer.authorize(behavior_class, SafetySnapshot)
      │
      ├── speech/informational → always GRANTED (no safety gate needed)
      ├── navigation_intent_classes → GRANTED only if SafetyState in {NORMAL, DOCKING}
      │                                and navigation_permitted
      └── actuation_intent_classes → GRANTED only if SafetyState == NORMAL
                                       and actuation_permitted
      v
behavior_engine_node (the only decision layer) constructs BehaviorDecision/
ActuationGesture
      v
ActuationSafetyGate.is_allowed() — re-checked at dispatch, independent of
the authorizer's earlier check (defense in depth)
      v
Physical actuator / navigation goal
```

The LLM **never** constructs `BehaviorDecision`/`ActuationGesture` directly
— confirmed by grep (only `bonbon_behavior_engine` constructs either) and
re-verified by `tests/production/test_behavior_engine_scenarios.py`'s
`llm_no_direct_action` oracle check on every run.

## 5. Final safety validation flow

```
Sensor/perception input
      v
Safety Supervisor (SafetyPolicy from safety_policy.yaml)
      │
      ├── NORMAL      → enable_actuation
      ├── CAUTION      → cap_velocity, announce_audio, notify_operator
      ├── DANGER       → zero_velocity, disable_actuation, log_incident
      ├── FAULT        → zero_velocity, disable_actuation, request_human_help
      ├── SAFE_STOP    → trigger_estop, log_incident, notify_operator
      └── DOCKING      → announce_audio, update_display
      v
SafetyState broadcast (transient-local, exactly one publisher — enforced
by the boot-topology guard, see section 9)
```

Boot-topology guard (systemd `Conflicts=`, mode scripts, static + runtime
validators) ensures the precondition "exactly one Safety Supervisor" holds
before this flow can even start. Detail: [BOOT_TOPOLOGY_FIX_REPORT.md](BOOT_TOPOLOGY_FIX_REPORT.md).

## 6. Final dashboard/API flow

```
Frontend (React/Vite) ──HTTP──> bonbon_operator_api (/api/v1/...)
                       ──WS───> /ws/{channel}  (robot-status, safety-events,
                                 navigation-events, diagnostics, live-logs,
                                 + this release's new channels: boot-topology,
                                 ai-runtime, pi-efficiency, validation,
                                 deployment-readiness)

bonbon_operator_api reads:
  - live ROS2 state (status_aggregator, when ROS2 is connected)
  - devops/project-status/*.json (boot topology, known issues, test results)
  - tests/scenarios/generated_scenarios/ (scenario catalog)
  - bonbon_behavior_validation / bonbon_field_learning stores directly
    (in-process Python import, not a separate service)

Every endpoint honestly reports `available: false` rather than fabricating
data when its backing source is missing — see [DASHBOARD_FINALIZATION_REPORT.md](DASHBOARD_FINALIZATION_REPORT.md).
```

## 7. Final Raspberry Pi runtime profile

`config/pi_efficiency_profile.yaml` — the frozen 17-item priority order
(rank 1 = never shed, highest rank = shed first under pressure):

1. Safety Supervisor · 2. Emergency stop polling · 3. HAL · 4. Lidar/obstacle
safety · 5. Navigation safety · 6. Active person tracking · 7. Object/person
detection · 8. Gesture · 9. Speech/VAD · 10. STT · 11. Human-state fusion ·
12. TTS · 13. Dashboard · 14. RAG · 15. LLM · 16. Background emotion ·
17. Analytics/logging.

Default FPS/throttle limits and the full policy set (bounded queues, stale-
frame dropping, CPU/thermal shedding, degraded mode) are frozen in that
file; verification in [PI_EFFICIENCY_PROFILE_REPORT.md](PI_EFFICIENCY_PROFILE_REPORT.md).

## 8. Final AI model runtime map

`config/runtime/model_runtime.yaml` (mode + per-model runtime priority),
`config/runtime/pi_ai_hat.yaml` (Hailo-preferred profile),
`config/runtime/pi_cpu_fallback.yaml` (CPU-only profile),
`config/runtime/degraded_mode.yaml` (shed order under AI-runtime pressure).
Runtime abstraction: `VisionModelRuntimeInterface` with `HailoRuntime` /
`CPUONNXRuntime` / `TensorRTRuntime` / `MockRuntime`, selected by
`RuntimeSelector(auto|hailo|cpu|tensorrt|mock)`. Detail: [AI_HAT_RUNTIME_STRATEGY.md](AI_HAT_RUNTIME_STRATEGY.md).

## 9. Final deployment modes

Exactly two, mutually exclusive by systemd `Conflicts=`:

- **A. Monolithic (dev/sim/lab):** `bonbon-core.service` runs
  `bringup.launch.py` (the whole stack including Safety Supervisor); all 8
  per-subsystem services disabled.
- **B. Modular Pi (production):** `bonbon-core.service` disabled;
  `bonbon-safety.service` is the single Safety Supervisor; selected
  per-subsystem services (`bonbon-hal`, `bonbon-perception`,
  `bonbon-speech`, `bonbon-behavior`, `bonbon-navigation`,
  `bonbon-actuation`, `bonbon-tts`) enabled as needed;
  `bonbon-dashboard`/`bonbon-monitoring` run in either mode (shared,
  non-duplicating).

Selection: `sudo bash scripts/select_deployment_mode.sh {monolithic|modular_pi}`.
No third mode exists in this release; a mixed enablement is rejected by
`classify_topology()` as `INVALID`, not silently tolerated.

## 10. Final known limitations

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for the complete, current
list (sourced live from `devops/project-status/known_issues.json`, not
duplicated here to avoid the two drifting apart). Headline items: 7 of 11
dashboard commands have no real ROS2 backend yet (honestly report
unavailable); `bonbon_vision`'s test suite needs a real `colcon build`
(generated interfaces) to collect in a non-ROS2-sourced environment; the
`bonbon_vision._build_detector()` → `RuntimeSelector` adapter is not yet
wired (Hailo/CPU selection is proven at the runtime-abstraction layer, not
yet consumed by the live vision node).

## POST-RELEASE (explicitly out of scope for this release candidate)

- `LLMQuery.srv` real server implementation (`rag_query` dashboard command).
- Software-triggered `emergency_stop`/`pause`/`resume`/`restart_module`/
  `get_config`/`set_config`/`memory_query` dashboard commands.
- `bonbon_vision._build_detector()` → `RuntimeSelector` live wiring.
- Finer-grained modular-mode service decomposition (vision/gesture/
  affective/speaker as independent services rather than bundled under
  `bonbon-perception`).
- `bonbon_actions/ExecuteMotionSequence.action` — defined, zero consumers.
- Real-ROS2 CI coverage for the 20 packages currently only covered by
  rclpy-stub pure-Python tests.
- Any new scenario families, endpoints, or modules beyond what's listed in
  sections 1-9 above.

Full roadmap and sequencing: [NEXT_RELEASE_ROADMAP.md](NEXT_RELEASE_ROADMAP.md).
