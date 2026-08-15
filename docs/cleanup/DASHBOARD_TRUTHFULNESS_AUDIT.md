# Dashboard Truthfulness Audit

**Phase 9.** Checks the brief's specific truthfulness rules against real code: fake green statuses, hardcoded OK, missing UNKNOWN/OFFLINE/BLOCKED/MISSING/FALLBACK_ACTIVE states, missing fallback reasons, broken WebSocket updates.

## Real bugs found (2) — both fixed this phase, see `DASHBOARD_FIX_REPORT.md`

1. **`restart_module`** (`diagnostics_api.py`) unconditionally returned `restart_requested: True` regardless of the bridge's actual (honest, `NOT_IMPLEMENTED`) result — a genuine "fake OK" per this audit's own rule #14 in `DANGEROUS_CODE_AUDIT.md`.
2. **`set_config`** (`config_api.py`) discarded the bridge propagation result entirely and unconditionally returned `updated: True` — same class of bug, notable because `CRITICAL_CONFIG_KEYS` includes safety-relevant parameters (`safety.emergency_distance_m`, `safety.watchdog_timeout_sec`) where an operator believing a change took effect on the robot when it didn't is a real operational risk, not just a cosmetic dashboard issue.

## Real gap found and fixed: advertised-but-nonexistent capability

3. **`live-logs` WebSocket channel** was listed in `VALID_CHANNELS`, permission-gated (`engineer+`), and documented in two module docstrings — but had zero producer anywhere in the codebase. A client with the right permission could subscribe and would receive nothing, forever, with no error. Fixed by removing the channel until a real log-stream producer exists (see `DASHBOARD_FIX_REPORT.md`) — the dashboard should not offer a capability it cannot deliver.

## Verified correctly honest (no action needed)

- **`ai_runtime_snapshot()`** — confirmed (via this repo's own `test_ai_runtime_snapshot_is_never_a_fake_hailo_pass` test, re-verified passing in this session's baseline) to report real `fallback_active=True`/honest `selected_kind` rather than claiming Hailo success without hardware. This is exactly the FALLBACK_ACTIVE rule the brief asks for, already correctly implemented.
- **The other 5 not-implemented commands** (`emergency_stop`, `pause`, `resume`, `memory_query`, `rag_query`) already correctly propagate bridge failure as HTTP 503 via `command_api.py`'s `_check_bridge_result` — this was itself a prior-session fix (see that function's own docstring/comment), and both new fixes in this phase now bring `diagnostics_api.py`/`config_api.py` in line with that already-established, already-tested pattern rather than inventing a new one.
- **28 of 29 WebSocket channels** compute real, non-fabricated payloads (verified via `test_status_broadcasters.py`'s "honest when missing" test suite) even though the current dashboard frontend only subscribes to one of them (`robot-status`). This is a dashboard-completeness gap (real backend work with no UI consumer), not a truthfulness violation — nothing here claims false data, it's simply unconsumed. Correctly left as QUARANTINE_UNVERIFIED in `DEAD_API_AND_ENDPOINT_REPORT.md`, not touched in this phase.
- **`bonbon_data_feedback`'s `debug_mode_enabled`** defaults to `false`, and raw snapshot persistence is only ever honored when explicitly enabled — the safe, honest default, confirmed in `CONFIG_CLEANUP_REPORT.md`.
- **Missing UNKNOWN/OFFLINE states**: `boot_topology_snapshot()`, `ai_runtime_snapshot()`, and `deployment_readiness_snapshot()` (all read directly during this and prior sessions' work) correctly return `available: False` with a message when their backing file/data doesn't exist, rather than defaulting to a false-positive `available: True`.

## Not touched: `restart_module`'s and `set_config`'s underlying capabilities are still not-implemented

Fixing the truthfulness bug does not make module restart or config propagation actually work — the underlying `bridge.call_restart_module`/`call_set_config` are still honest `NOT_IMPLEMENTED` stubs (see `docs/KNOWN_LIMITATIONS.md`). The fix ensures the dashboard now honestly reports that non-implementation as an HTTP 503 instead of a fake 200, which is this phase's actual scope — implementing real module-restart/config-propagation dispatch is a feature task, not a cleanup task.
