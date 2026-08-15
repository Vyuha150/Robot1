# Duplicate Pipeline Report

**Phase 3.** Checks the 20 pipeline categories from the cleanup brief against the "exactly one owner" hard rules. Builds directly on Phase 2's cluster research (re-verified, not re-derived from scratch) plus targeted checks for the categories Phase 2 didn't already cover (LiDAR, logging, config loading).

## Hard-rule compliance summary

| Rule | Status | Owner |
|---|---|---|
| Exactly one active Safety Supervisor per deployment mode | ✅ PASS | `bonbon_safety` (`safety_supervisor_node` + `safety_gate_node`) — monolithic and Pi-3/distributed modes both use it; `bonbon_distributed_safety` is non-authoritative heartbeat-only |
| Exactly one physical camera owner | ✅ PASS | `bonbon_vision` — sole package with camera driver code and model inference; `bonbon_perception` (dead duplicate) is disabled, not counted |
| Exactly one physical microphone owner | ✅ PASS | `bonbon_speech` — sole VAD/wake-word/STT node |
| Exactly one LiDAR owner | ✅ PASS | `bonbon_hal/nodes/lidar_node.py` — sole publisher; `bonbon_safety`/`bonbon_navigation`/`bonbon_simulation` are subscribers only |
| Exactly one motor execution authority | ✅ PASS | `bonbon_hal`'s motor/servo/stepper drivers, reachable only via `bonbon_safety`'s gated topics — no bypass found anywhere in the repo (see `DANGEROUS_CODE_AUDIT.md`) |
| UI/LLM never directly control motors/servos/Nav2 | ✅ PASS | Verified by direct grep: `bonbon_llm`, `bonbon_operator_api`, `bonbon_patient_kiosk` have zero `cmd_vel`/servo-command/NavigateToPose-client publishers |
| AI Pi only publishes behavior proposals | ✅ PASS | `bonbon_behavior_engine` (runs on AI Pi in distributed mode) publishes only to `/bonbon/behavior/proposal` and `/bonbon/behavior/actuation` (itself gated) |
| Navigation/Safety Pi is the only movement authority | ✅ PASS | `bonbon_motion_approval_gateway`, `bonbon_navigation`, `bonbon_safety`, `bonbon_hal` (motor-bearing) all run on the Nav/Safety Pi per `bonbon_navigation_bringup` |

**All 8 hard rules pass with real evidence, not just design intent.** This is the single most important result of Phase 3 — the architecture this repo has been describing in its docs is genuinely implemented as described.

## Per-category findings

| Category | Duplicate found? | Detail |
|---|---|---|
| 1. Safety Supervisor | No | `bonbon_safety` sole authority; `bonbon_distributed_safety`/`bonbon_authority_manager` are complementary (liveness reporting + advisory broadcast), not competing supervisors — both explicitly disclaim decision authority in their own docstrings |
| 2. Camera pipeline | **Yes — already inert** | `bonbon_perception` fully duplicates `bonbon_vision`'s camera+detection+face pipeline, but is disabled (launch file `.disabled`, empty console_scripts, zero imports). See Removal Plan below |
| 3. Microphone pipeline | No | `bonbon_speech` sole owner; `bonbon_speech_ai` has no audio-device code, it's a downstream text/routing library |
| 4. LiDAR pipeline | No | `bonbon_hal/nodes/lidar_node.py` sole publisher |
| 5. Motor control pipeline | No | Sole path: proposal → gateway → gate → HAL |
| 6. Servo control pipeline | No | Same gated path as motor; `bonbon_actuation` publishes only pre-gate `*_raw` topics |
| 7. Object detection | No (real fix confirmed still holding) | GAP-E10's consolidation verified still in effect — `bonbon_object_intelligence`/`bonbon_perception_ai` consume `bonbon_vision`'s output, no re-implementation found |
| 8. Face recognition | **Yes — same inert duplicate** | Only present in the dead `bonbon_perception`; live `bonbon_vision` is sole owner |
| 9. Gesture recognition | No | `bonbon_gesture` sole owner |
| 10. Affective AI | No | `bonbon_affective_ai` sole owner |
| 11. Human-state fusion | No | `bonbon_human_state_fusion` explicitly disclaims re-deriving emotion/gesture already computed elsewhere |
| 12. LLM gateway | No | `bonbon_llm` sole orchestrator; `bonbon_edge_ai_runtime`'s task router sits upstream of it (routing decision), not a competing gateway |
| 13. RAG service | No | Owned within `bonbon_llm`/`bonbon_data_stores`, no second implementation found in this pass |
| 14. Dashboard backend | **No, but real code duplication in a supporting layer** | `bonbon_operator_api` (staff) and `bonbon_patient_kiosk` (patient) are two *legitimately separate* backends for different audiences — not duplicate dashboards — but their **auth implementations** are a confirmed copy: `bonbon_patient_kiosk/auth/auth_manager.py`'s own docstring says "Pattern-copied from bonbon_operator_api.auth.auth_manager" |
| 15. Robot bridge | No | Not identified as a separate concept in this codebase beyond `bonbon_operator_api`'s `ros2/ros2_bridge.py` (single instance) |
| 16. Database/session management | Partial (see #14) | `bonbon_data_stores` is the one shared persistence layer; `operator_api` and `patient_kiosk` each additionally maintain their own separate SQLite DBs for domain-specific data (patient intake vs. operator audit) — not itself wrong, but the auth-table duplication rides on top of it |
| 17. Logging | No | Standard per-package `logging.getLogger(__name__)` usage via rclpy's node logger — no competing logging framework found |
| 18. Config loading | No | Each package uses its own dataclass + `declare_parameter`/`from_ros_params` pattern consistently — this is this repo's established convention, not duplication |
| 19. System health monitoring | No | `bonbon_fault_manager` is the single aggregation point; `bonbon_hardware_telemetry` and `bonbon_distributed_network_monitor` are two distinct, non-overlapping *sources* feeding into it (device metrics vs. network/clock health), not duplicate monitors of the same thing |
| 20. Deployment/systemd services | **Needs Phase 8 resolution, not concluded here** | Two launch mechanisms exist (`*_bringup` packages vs. `launch/edge_ai/*_pi_edge.launch.py`) — both real, relationship (layered vs. overlapping) not yet confirmed against actual systemd unit files |

## The one real, actionable duplicate: `bonbon_perception`

This is the only genuine duplicate-pipeline finding in the entire 44-package tree. Everything else that looked like potential duplication on a first name-based pass (`bonbon_perception` vs `_ai` vs `_efficiency` vs `_vision`; `bonbon_ai_runtime` vs `_edge_ai_runtime`; the 4 `*_bringup` packages; `operator_api` vs `patient_kiosk`) turned out to be legitimately distinct scopes on inspection, several with their own README/docstring already documenting the non-overlap by design.

`bonbon_perception` reimplements `bonbon_vision`'s entire camera+YOLO+face pipeline independently, subscribing to the same raw camera topic. It is fully disabled (launch file renamed to `.disabled`, `setup.py`'s `console_scripts` emptied) and has zero repo-wide importers — someone already recognized the duplication and neutered it, but never deleted the package. See `REDUNDANT_CODE_REMOVAL_PLAN.md` for the removal plan.

## Secondary finding: auth duplication between operator_api and patient_kiosk

Real code duplication (JWT/PBKDF2/SQLite auth pattern, explicitly self-documented as copied), but **not a safety or dashboard-truthfulness issue** — the two systems correctly serve different audiences with different role models (4-role staff vs. 2-role kiosk) and different databases. This is a maintainability concern (a security fix in one auth implementation won't automatically apply to the other) worth a dedicated future refactor task, not an in-scope removal for this cleanup pass. See Removal Plan.
