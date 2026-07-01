# Known Limitations

Sourced live from [`devops/project-status/known_issues.json`](../devops/project-status/known_issues.json)
(also served at `GET /api/v1/diagnostics/known-issues` and
`GET /api/v1/deployment/known-issues`) — this document summarizes it, it
does not duplicate the authoritative data. If the two ever disagree,
trust the JSON file and update this page.

## Blocking (`blocking_deployment: true`)

| ID | Title | Why it's still blocking |
|---|---|---|
| `bonbon_vision_test_hang` | `bonbon_vision`'s test suite cannot collect in this environment | Re-verified 2026-07-01: fails at collection with `ImportError: cannot import name 'PerceptionBudget' from 'bonbon_msgs.msg'` — that message type only exists after a real `colcon build` generates `bonbon_msgs`' interfaces. Cannot be fixed or worked around without a sourced ROS2 workspace. |
| `dashboard_commands_partially_unimplemented` | 7 of 11 dashboard commands have no real ROS2 backend | `emergency_stop` (hardware/GPIO e-stop only, no software trigger exists anywhere), `pause`, `resume`, `restart_module`, `get_config`, `set_config`, `memory_query`, `rag_query` all honestly report unavailable rather than faking success. `navigate`, `cancel_task`, `dock`, `speak` are real. |

## Resolved this release (kept for audit trail, no longer blocking)

| ID | What was fixed |
|---|---|
| `systemd_duplicate_safety_supervisor` | Four-layer boot-topology guard (systemd `Conflicts=`, mode scripts, static validator, runtime check) — see [BOOT_TOPOLOGY_FIX_REPORT.md](BOOT_TOPOLOGY_FIX_REPORT.md). |
| `no_hailo_ai_hat_backend` | `bonbon_ai_runtime` runtime abstraction (Hailo/CPU/TensorRT/Mock) — see [AI_HAT_RUNTIME_REPORT.md](AI_HAT_RUNTIME_REPORT.md). Vision-node wiring itself is a separate, non-blocking POST-RELEASE item. |

## Non-blocking, documented

- **`bonbon_vision._build_detector()` → `RuntimeSelector` wiring not yet done.** The runtime abstraction is proven independently (30 tests); the live vision node doesn't yet select through it. POST-RELEASE.
- **`ci_coverage_gap`** — 20 of 26 packages have no real-ROS2 CI coverage, only pure-Python rclpy-stub tests.
- **`ad_hoc_sqlite_connections`** — 5 modules manage independent `sqlite3.connect()` for genuinely different concerns (not redundant pipelines).
- **`bonbon_actions_unused_interface`** — `ExecuteMotionSequence.action` defined, zero consumers.
- **`operator_api_test_suite_slow`** — the dashboard's test suite takes 1-4 minutes vs. <2s for other packages (likely real network/sleep waits in WebSocket tests); not a failure, worth a follow-up.
- **`perception_quarantined`** — `bonbon_perception` intentionally superseded and disabled; correctly marked, not a defect.

## What genuinely requires physical hardware to close out

Every item in [HARDWARE_GATED_TESTS.md](HARDWARE_GATED_TESTS.md) and every
`BLOCKED` row in [FINAL_PRODUCTION_READINESS_CHECKLIST.md](FINAL_PRODUCTION_READINESS_CHECKLIST.md)
— live boot-topology confirmation, real Hailo inference, physical e-stop
latency under full AI load, measured thermal/CPU stability, and the full
sensor/multi-person/gesture/speech accuracy suite in a real room.
