# Dashboard Fix Report

**Phase 9.** The three real fixes applied, with evidence they're correct.

## Fix 1: `restart_module` now honestly reports bridge dispatch failure

**File:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/diagnostics_api.py`

Imported `_check_bridge_result` from `command_api.py` (the same helper already proven correct for `/robot/commands/*`, rather than reimplementing it) and applied it to the bridge result before responding. A failed restart now raises HTTP 503 with the bridge's error detail, matching what the audit log already recorded, instead of unconditionally claiming `restart_requested: True`.

**Test:** `test_restart_reports_bridge_dispatch_failure` (new, `test_diagnostics.py`) — mocks the bridge to return `{"success": False, "error": "NOT_IMPLEMENTED"}` and asserts HTTP 503. The pre-existing `test_engineer_restart_valid_module` (asserting 200 + `restart_requested: True` when the bridge succeeds) continues to pass unchanged, since the test fixture's default mock bridge returns `{"success": True}`.

## Fix 2: `set_config` now honestly reports ROS2 propagation failure

**File:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/config_api.py`

Same `_check_bridge_result` pattern applied to `bridge.call_set_config(...)`'s return value. The local `_ConfigStore` JSON-file write (which is real and durable regardless of ROS2 connectivity) still happens first and is preserved even when the HTTP response reports 503 — a caller can retry propagation without re-entering the value. This matters most for `CRITICAL_CONFIG_KEYS` (`safety.emergency_distance_m`, `safety.watchdog_timeout_sec`, `navigation.max_speed_mps`, `navigation.obstacle_distance_m`): an admin changing a safety-critical parameter now gets an honest error if the robot never received the change, instead of a false "updated" confirmation.

**Tests:** New `test_config_api.py` (no dedicated test file existed for this router before this phase — a gap itself found in the Phase 4 audit) — 12 tests covering read/write/permission behavior plus 3 tests specifically pinning this fix: bridge-failure propagates as 503, the local store write survives a failed propagation, and a successful propagation still returns `updated: True`.

## Fix 3: `live-logs` WebSocket channel removed until a real producer exists

**Files:** `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/websocket/ws_manager.py`, `websocket/ws_router.py`

Removed `"live-logs"` from `VALID_CHANNELS` and `_CHANNEL_MIN_PERMISSION`, and from both files' module docstrings. Before this fix, an `engineer`+ user could successfully subscribe to this channel (permission check passes, connection accepted) and would then receive nothing, ever, with no error — a real, if minor, instance of advertising a capability that doesn't exist. No frontend anywhere subscribes to it (confirmed in Phase 4's dead-channel audit), so removal has zero user-facing impact today. Re-adding it is a one-line change once a real log-stream producer is built — this fix doesn't foreclose the feature, it just stops claiming it exists before it does.

## What was deliberately NOT fixed in this phase

- **The underlying `restart_module`/`set_config` capabilities are still not-implemented** at the ROS2 bridge layer — this phase made the dashboard honest about that fact, it didn't implement the missing functionality (a real feature task, out of scope for a cleanup pass).
- **The other 28 WebSocket channels with zero frontend consumers** — real, honest, tested backend work; a dashboard-completeness gap, not a truthfulness violation. Left for a future task to either build UI for or consciously deprioritize.
- **`get_config`'s HTTP-layer failure propagation** — not independently re-verified in this phase (see `DEAD_API_AND_ENDPOINT_REPORT.md`'s note); flagged for a follow-up check rather than assumed fixed or broken.

## Verification

- `test_config_api.py`: 12/12 passing.
- `test_diagnostics.py`: full file re-run, all passing including the new failure-propagation test.
- `ruff check` / `black --check`: clean on all 6 touched files.
- Full `bonbon_operator_api` suite re-run for regressions — see `POST_CLEANUP_TEST_REPORT.md` (Phase 12) for the consolidated result.
