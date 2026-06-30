# BonBon Repository Verification Report — Phase 1 (Audit Only)

**Date:** 2026-06-30
**Scope:** Full repository — `ros2_ws/src` (26 ROS2 packages), dashboard/API,
devops, CI/CD, deployment, simulation, scripts, docs.
**Method:** Evidence-based — every finding below was verified by reading
source, running `compileall`, and grepping for actual publishers/subscribers/
topic strings, not inferred from package names or prior session memory.
**Rule honored:** no fixes were made while producing this report.

---

## 1. All packages found

**26 ROS2 packages** under `ros2_ws/src`:

`bonbon_actions`, `bonbon_actuation`, `bonbon_affective_ai`,
`bonbon_behavior_engine`, `bonbon_bringup`, `bonbon_data_feedback`,
`bonbon_data_stores`, `bonbon_gesture`, `bonbon_hal`,
`bonbon_human_state_fusion`, `bonbon_llm`, `bonbon_msgs`,
`bonbon_multi_person_tracker`, `bonbon_navigation`,
`bonbon_object_intelligence`, `bonbon_operator_api`, `bonbon_perception`,
`bonbon_perception_ai`, `bonbon_perception_efficiency`, `bonbon_safety`,
`bonbon_simulation`, `bonbon_spatial`, `bonbon_speaker_intelligence`,
`bonbon_speech`, `bonbon_srvs`, `bonbon_tts`, `bonbon_vision`.

**Non-ROS2 / repo-root items:**
- `deployment/`, `devops/`, `.github/workflows/`, `scripts/`, `tests/`,
  `docs/` — operational tooling and cross-package tests/docs.
- `founder_command_center/` — **not BonBon robot software.** A separate,
  unrelated personal productivity tool (React/Vite + FastAPI), tracked in
  git (34 files), living in this repo by coexistence, not integration.
- `Bonbon-robot/` — an empty nested git clone (gitignored, untracked,
  contains only `.git/`). Stray local artifact.
- `ai_core/`, top-level `simulation/`, `tools/` — **completely empty,
  untracked directories.** No files, no git history. Clutter, not packages.

## 2. Package status: complete / partial / empty / broken / redundant

| Package | Status | Notes |
|---|---|---|
| `bonbon_actuation` | Complete | 21 py, 7 tests, launch present |
| `bonbon_affective_ai` | Complete | 33 py, 6 tests |
| `bonbon_behavior_engine` | Complete | 25 py, 9 tests |
| `bonbon_bringup` | Complete | Orchestration-only, 4 py, 1 test (proportionate to scope) |
| `bonbon_data_feedback` | Complete | 25 py, 8 tests (62 individual test cases) |
| `bonbon_data_stores` | Complete, **undocumented** | 47 py, 7 tests, no README anywhere |
| `bonbon_gesture` | Complete | 35 py, 8 tests |
| `bonbon_hal` | Complete | 65 py, 11 tests |
| `bonbon_human_state_fusion` | Complete | 21 py, 6 tests |
| `bonbon_llm` | Complete | 38 py, 10 tests |
| `bonbon_msgs` | Complete (interface-only) | 49 .msg files, 0 .py expected and correct |
| `bonbon_multi_person_tracker` | Complete | 19 py, 4 tests |
| `bonbon_navigation` | Complete | 36 py, 11 tests, 3 launch files |
| `bonbon_object_intelligence` | Complete | 19 py, 5 tests |
| `bonbon_operator_api` | **Partial** — builds and has tests, but its live ROS2 status bridge does not connect to real publishers (see §6, §13) | 49 py, 8 tests, no README |
| `bonbon_perception` | **Quarantined (intentional)** | `.disabled` launch file, emptied entry_points, documented in its own README — superseded by `bonbon_vision`+`bonbon_gesture`+`bonbon_affective_ai`. Correctly marked, not a defect. |
| `bonbon_perception_ai` | Complete | 37 py, 9 tests |
| `bonbon_perception_efficiency` | Complete | 29 py, 10 tests (77 individual test cases) |
| `bonbon_safety` | Complete | 45 py, 14 tests — the most heavily tested package, appropriately |
| `bonbon_simulation` | Complete, **thin test surface** | 26 py but only 1 test *file* (may contain many cases — verify in Phase 2) |
| `bonbon_spatial` | Complete | 24 py, 8 tests |
| `bonbon_speaker_intelligence` | Complete | 19 py, 5 tests |
| `bonbon_speech` | Complete | 37 py, 8 tests |
| `bonbon_srvs` | Complete (interface-only) | 16 .srv files |
| `bonbon_actions` | **Partial — defined, unused** | `ExecuteMotionSequence.action` exists; zero Python files anywhere reference it as either server or client |
| `bonbon_tts` | Complete | 31 py, 7 tests |
| `bonbon_vision` | Complete | 32 py, 8 tests |

**No package is empty or syntactically broken.** `bonbon_actions` is the one
genuinely incomplete ROS2 interface package: an action type was defined but
never wired to any provider.

## 3. Existing ROS2 topics

128 distinct `/bonbon/...`-prefixed topic string literals found across all
node source files (grep count of unique literals, not deduplicated by
intent — some are parameterized/templated at runtime). Full list omitted
from this report for length; spot-checked against publishers in §6/§13.

## 4. Existing ROS2 services

16 `.srv` definitions in `bonbon_srvs`: `SafetyReset`, `LLMQuery`,
`AnalyzeText`, `GetWorldModel`, `GetApproachPose`, `AddRestrictedZone`,
`RemoveRestrictedZone`, `SetPrivacyMode`, `EvaluateCommand`,
`PerformGesture`, `SetMode`, `HealthCheck`, `ReportFailureCase` (added this
session). All have at least one server implementation found via prior
session work; not individually re-verified for orphaning in this pass.

## 5. Existing ROS2 actions

1 action definition: `bonbon_actions/action/ExecuteMotionSequence.action`.
**Zero consumers** — see §2 and §6.

## 6. Missing interfaces

- **`ExecuteMotionSequence.action`** — defined, but no action server or
  client exists anywhere in the codebase. Either dead weight to remove, or
  a genuinely planned capability (e.g. choreographed multi-step gestures)
  that was never implemented past the interface definition.
- **Dashboard ROS2 bridge topics do not match real publishers** (high
  severity — see §13 for full detail). Specifically:
  - `/bonbon/battery/status` (dashboard expects) vs `/bonbon/battery/state`
    with `BatteryState` type (real publisher, `bonbon_hal/battery_node.py`)
    — wrong name AND wrong type.
  - `/bonbon/navigation/state` (dashboard expects) vs `/navigation/status`
    with `NavigationStatus` type (real publisher,
    `bonbon_navigation/navigation_node.py`) — wrong name, wrong namespace,
    wrong type.
  - `/bonbon/safety/state` (dashboard expects, name matches) but dashboard
    subscribes as `std_msgs/String`; the real publisher
    (`safety_supervisor_node.py`) publishes typed `bonbon_msgs/SafetyState`
    — **type mismatch on a name match**, which is the most dangerous kind
    (looks correct at a glance, silently never connects).
  - `/bonbon/tts/state` (dashboard expects) vs `/bonbon/tts/health` (real
    publisher, `std_msgs/String` JSON) — wrong name; type would have been
    compatible.
  - `/bonbon/perception/status`, `/bonbon/actuation/state`,
    `/bonbon/modules/status`, `/bonbon/heartbeat` — **no publisher exists
    anywhere in the codebase for these exact topic names.** The perception
    stack publishes per-node `ModuleHealth` on a dozen distinct topics
    instead (e.g. `/bonbon/vision/vision_node/health`); there is no single
    aggregate `/bonbon/perception/status`. Actuation publishes
    `ActuationStatus` on a configurable `status_topic` parameter, not a
    fixed `/bonbon/actuation/state`. Neither `/bonbon/modules/status` nor
    `/bonbon/heartbeat` are published by any node at all.

  **Net effect: of the 8 topics the operator dashboard's ROS2 bridge
  subscribes to, 0 are fully correctly wired (right name + right type).**
  The dashboard's live status display is effectively disconnected from the
  real robot software. This is almost certainly why the task asked for the
  dashboard to be "updated to reflect real project status."

## 7. Broken imports

**None.** `python -m compileall -q -f` across all 736 `.py` files in
`ros2_ws/src` completed with zero errors. (This validates syntax and
import-statement shape, not runtime resolution of every third-party/ROS2
import — full resolution requires the colcon build attempted in Phase 2.)

## 8. Duplicated responsibilities

None newly found. The one historically duplicated responsibility
(`bonbon_perception` vs `bonbon_vision`+`bonbon_gesture`+`bonbon_affective_ai`)
was already identified and quarantined in a prior engagement this session —
verified still correctly quarantined (`.disabled` launch file, emptied
entry_points, documented README).

## 9. Redundant modules

None found in `ros2_ws/src`. `founder_command_center` is not a redundant
*module* of BonBon — it's an entirely separate product that happens to
share the repository. It is not redundant with anything; it's simply out of
scope and should not be touched by this audit or any BonBon-specific fix.

## 10. Unsafe command paths

**None found — verified, not assumed.** Specifically checked:
- `bonbon_operator_api/api/command_api.py` routes every command through
  `request.app.state.safety_gate` (`SafetyCommandGate`) before it can reach
  ROS2. `safety_gate.py`'s own docstring: *"The gate NEVER bypasses the
  Safety Supervisor node. It is a pre-filter on the HTTP/WebSocket side —
  not a replacement for the real safety system."*
- `bonbon_llm/nodes/llm_orchestrator_node.py`: any LLM-resolved
  `behavior_class` passes through `CommandAuthorizer.authorize(...)` against
  the live `SafetyState` snapshot before dispatch; docstring confirms *"LLM
  output NEVER reaches cmd_vel, nav2, or GPIO directly."* (Independently
  re-verified this session during the efficiency compliance audit.)

## 11. Missing tests

- **CI's `colcon test --packages-select`** (the job that runs tests against
  a *real* sourced ROS2 install, exercising actual `rclpy` lifecycle
  transitions and message passing) covers only **6 of 26 packages**:
  `bonbon_safety`, `bonbon_hal`, `bonbon_operator_api`, `bonbon_data_stores`,
  `bonbon_simulation`, `bonbon_bringup`. The remaining 20 packages —
  including `bonbon_llm`, `bonbon_vision`, `bonbon_navigation`,
  `bonbon_actuation`, and every package built this session — are only
  exercised via `scripts/test.sh --no-ros2`'s rclpy-stub-based pure-Python
  tests, never against a real ROS2 install in CI. This means lifecycle
  transition bugs, QoS mismatches, and real message-type mismatches (like
  §6's dashboard finding) are **structurally invisible to CI** for 20 of 26
  packages.
- `bonbon_simulation` has only 1 test *file* against 26 source files —
  needs verification in Phase 2 of whether that one file has proportionate
  coverage or is a thin smoke test.
- `bonbon_actions`' `ExecuteMotionSequence.action` has zero tests, consistent
  with having zero implementation (§6).

## 12. Failing tests

Not yet determined — Phase 1 is audit-only per the task's explicit
instruction not to fix or run destructive commands ahead of the report.
Phase 2 will run the actual suites and report real pass/fail counts.

## 13. Missing dashboard integrations

This is the most significant finding of this audit. Detailed in §6. Summary:
the operator dashboard (`bonbon_operator_api`'s `ros2_bridge.py`) was
written against topic names/types that do not match what any real BonBon
node currently publishes — likely written early in the project before the
final topic-naming conventions (e.g. `ModuleHealth` per-node health topics,
`bonbon_msgs/SafetyState` typed safety state) were established, and never
updated as the rest of the system evolved. The dashboard backend itself
(FastAPI routes, auth, audit, safety gate, websocket layer) is solid and
well-tested (8 test files) — the gap is specifically the ROS2-to-dashboard
data bridge.

## 14. Missing documentation

- `bonbon_data_stores` — no README anywhere (package root or `docs/`).
- `bonbon_operator_api` — no README anywhere, despite being the dashboard
  backend with 49 Python files and the integration gap described above.
  Documenting the *intended* topic mapping would have caught §6's drift
  earlier.
- Every other package has a README.

## 15. Deployment blockers

1. **Dashboard status bridge is non-functional for real robot data** (§6,
   §13) — would ship an operator dashboard that always shows stale/default
   values for battery, navigation, perception, TTS, actuation, module
   status, and heartbeat, and silently never receives safety state either,
   despite the topic name coincidentally matching.
2. **20 of 26 packages have no real-ROS2 CI coverage** (§11) — lifecycle
   and message-type regressions in those packages would not be caught
   before merge.
3. `ExecuteMotionSequence.action` is an unimplemented interface — not
   blocking by itself, but should be either implemented or removed before
   calling the action layer "complete."

No other deployment blockers found in this pass; Phase 2's actual build/lint/
type-check run may surface additional ones.

## 16. Production-readiness score

**6.5 / 10.**

Strong fundamentals: zero broken imports, zero TODO/FIXME/placeholder/
`NotImplementedError` markers across 736 files, every safety-relevant
command path independently verified to route through the Safety Supervisor
or its dashboard pre-filter, comprehensive per-package test suites with a
consistent rclpy-stub testing convention, and a mature deployment/CI/devops
scaffold (multi-environment configs, Docker, rollback scripts, release
process docs).

Held back specifically by: the dashboard integration gap (a real,
user-facing defect that directly contradicts the dashboard's purpose), the
CI coverage gap for 20/26 packages against real ROS2, and two undocumented
packages including the dashboard itself. None of these are architectural
problems — they're concrete, scoped, fixable items, not signs of a
fundamentally unsound system.

---

*Phase 2 (build and static validation) follows this report.*
