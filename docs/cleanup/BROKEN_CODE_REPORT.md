# Broken Code Report

**Phase 4.** No import-time crashes exist anywhere in the 44-package tree (AST-checked, 1,505 cross-package imports verified). What follows are real, narrower defects — some latent (guarded, don't crash today, but are wrong), some active (return wrong information to a caller).

## FIX_NOW

### 1. `restart_module` endpoint fakes success on failure

**File:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/diagnostics_api.py:63-74`

`call_restart_module(...)` is one of the 7 documented not-yet-implemented dashboard commands (`ros2_bridge.py:445-452`, honestly returns `{"success": False, "error": "NOT_IMPLEMENTED"}`). The endpoint logs the honest `outcome="failure"` to the audit trail, then **unconditionally** returns HTTP 200 `APIResponse.ok({"restart_requested": True})` regardless of what the bridge call actually returned. The audit log says failure; the HTTP response says success — a direct contradiction. `tests/test_diagnostics.py:28-34` currently asserts `restart_requested is True`, enshrining the bug rather than catching it. Contrast with `command_api.py`'s `_check_bridge_result` helper (lines 68-80), which correctly raises HTTP 503 on `success: False` for the `/robot/commands/*` routes — the fix is to apply that same pattern here.

### 2. `set_config_key` endpoint discards the bridge result entirely

**File:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/config_api.py:136-154`

`PUT /api/v1/config/` calls `bridge.call_set_config(key, body.value)` — also routed through `_not_implemented()` — and never inspects the return value at all. It unconditionally returns `{"updated": True}`. Since this endpoint currently has zero callers (see `DEAD_API_AND_ENDPOINT_REPORT.md`), the bug is latent, but must be fixed as part of whatever decision is made about this endpoint's fate (wire it up for real, or remove it — either way, don't leave a fake-success response in place).

**Both of these are exactly the "fake dashboard OK status" / "fake hardware PASS" pattern this cleanup brief calls out as dangerous.** Real fixes (not just documentation) land in Phase 9 (`DASHBOARD_FIX_REPORT.md`), where the dashboard-truthfulness rules apply.

### 3. `@types/react`/`@types/react-dom` major-version mismatch

**File:** `ros2_ws/src/bonbon_operator_api/frontend/package.json:20-21`

Dev-dependency type packages pinned to `^19.2.15`/`^19.2.3` against a runtime `react`/`react-dom` pinned to `^18.3.1` (same file, lines unspecified in the actual dependency block). This is either a leftover from an aborted React 19 upgrade or a typo — either way it means the TypeScript compiler is checking against the wrong React API surface. Low risk to fix (revert to `^18.x` types, or do the real upgrade), but should not be left silently mismatched.

## FIX_NOW (packaging/architecture — moderate effort, not a one-line fix)

### 4. `validation_api.py` imports two repo-root packages that aren't deployable

**File:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/validation_api.py:196-197, 252, 281, 309, 356, 388, 469-470`

Imports `bonbon_behavior_validation` and `bonbon_field_learning` — both real packages, but they live at the **repo root** (`./bonbon_behavior_validation/`, `./bonbon_field_learning/`), not inside `ros2_ws/src/`, have no `package.xml`/`setup.py`, and aren't declared as installable in `pyproject.toml`. A colcon-built/containerized `bonbon_operator_api` has no `PYTHONPATH` route to them. Every import site is correctly wrapped in `try/except ImportError` returning `{"available": False}` — so this degrades honestly rather than crashing — but it means `/validation/production-score`, `/field-learning/*`, and `/datasets/status` will **always** report unavailable in any real deployment, not just in this dev sandbox. Needs a packaging decision (make them installable packages, or accept these are dev-only endpoints and document that explicitly) — not resolved in this cleanup pass, flagged for a follow-up task.

## QUARANTINE (structural drift risk, not currently broken)

### 5. Two launch files are functionally dead — real boot logic duplicated inline instead

**Files:** `ros2_ws/src/bonbon_authority_manager/launch/authority_manager.launch.py`, `ros2_ws/src/bonbon_distributed_safety/launch/distributed_safety.launch.py`

Zero `IncludeLaunchDescription` references to either file anywhere in the repo. Both `bonbon_human_ai_bringup/launch/human_ai_bringup.launch.py:159-174` and `bonbon_navigation_bringup/launch/navigation_bringup.launch.py:97-112` construct the equivalent `LifecycleNode(...)` **inline** instead of including these package-owned launch files. The package-level launch files are fully correct and functional — they're just never invoked, meaning there are now two independent definitions of how to launch the same nodes, which will silently drift out of sync if one is edited and not the other. Recommend either deleting the two orphaned files (since the inline versions are what's actually deployed) or refactoring the bringups to `include` them (single source of truth) — a real decision for Phase 8, not resolved here.

### 6. Legacy flat systemd services duplicate the 3-Pi split

**Files:** `deployment/systemd/{bonbon-core,bonbon-actuation,bonbon-behavior,bonbon-dashboard,bonbon-hal,bonbon-monitoring,bonbon-navigation,bonbon-perception,bonbon-safety,bonbon-speech,bonbon-tts}.service` (11 files)

Already documented as pre-3-Pi-split legacy in `docs/THREE_PI_RUNTIME_AUDIT.md:133-136` — not a new finding, but confirmed still present and confirmed that `devops/scripts/post_deploy_check.py` only checks 8 of these 11 legacy names, none of the `pi1/pi2/pi3/*.service` ones. Ties directly into the "two launch mechanisms" open question from `DUPLICATE_PIPELINE_REPORT.md` — Phase 8 will resolve which systemd layer is actually deployed per Pi.

## KEEP (checked, found sound)

- No empty skeleton packages, no TODO-only files, no large commented-out code blocks anywhere in the 44-package tree.
- `bonbon_perception` (already known dead) excluded from this scan — see `DUPLICATE_PIPELINE_REPORT.md`.
