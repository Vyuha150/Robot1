# Dead API and Endpoint Report

**Phase 4** (feeds Phase 9's dashboard-truthfulness fixes directly). Every REST endpoint and WebSocket channel in `bonbon_operator_api` and `bonbon_patient_kiosk` checked against real frontend usage — literal path/channel-name strings grepped in each app's own `src/`, not inferred from naming.

## `bonbon_operator_api` — REST endpoints

### REMOVE — zero frontend usage AND zero test coverage
- `config_api.py:66,76,90` — `GET /api/v1/config/`, `GET /api/v1/config/{key}`, `PUT /api/v1/config/`
- `memory_api.py:34,48` — `POST /api/v1/memory/query`, `POST /api/v1/memory/rag/query`
- `ai_model_status_api.py` — all 12 routes (`ai-models/registry|status|download-plan|download/{id}|benchmark`, `speech-ai/status|asr|tts`, `sarvam/status`, `llm-local/status`, `perception-ai/status`, `affective-ai/status`, `gesture-ai/status`)
- `edge_ai_status_api.py` — all 9 routes
- `hardware_telemetry_api.py:24` — `GET /api/v1/hardware-telemetry/status`

### QUARANTINE — backend-tested, but no UI screen calls them (a dashboard gap, not dead code)
`distributed_api.py` (8 routes), `auth_api.py` user-management routes, `deployment_api.py` `select-mode`/`known-issues`/`readiness`, `diagnostics_api.py` `restart`/`audit`/`ws-connections`, `llm_test_api.py` `providers`, `testbench_api.py` `providers/check`/`sessions` GET routes. All real, all exercised by `TestClient` in CI — the dashboard simply never built a screen for user-management, distributed-topology, or provider-diagnostics.

### KEEP
Auth login/me, robot status/commands, deployment boot-topology/duplicate-node-check/ai-runtime/pi-status, validation, testbench status/client-output/sessions-POST/events/analysis — all tested and actively called from `App.tsx`.

## `bonbon_patient_kiosk` — REST endpoints (checked against its own frontend, not operator_api's)

- **REMOVE**: `appointment_api.py:66` `POST /api/v1/appointments/reschedule` — no client call, no test hit.
- **QUARANTINE**: `auth_api.py` `/auth/me`, `/auth/users` (GET/POST/PATCH/DELETE) — tested but the staff panel has no user-management UI.
- **KEEP_AS_TEST_MOCK**: `session_api.py:50` `GET /session/{id}` — tested, minor unused convenience route, not concerning.
- Everything else (session/consent/patient-lookup/intake/appointments-core/queue/chat/navigation/panic/feedback/facility-map/dashboard-overview) is actively called — KEEP.

## WebSocket channels — `bonbon_operator_api`

`ws_manager.py:35-71` defines **29 channels**. `App.tsx` opens exactly **one** WebSocket, hardcoded to `"robot-status"` (line 229). No other channel string appears anywhere in the frontend.

- **QUARANTINE (28 of 29 channels)** — `boot-topology`, `ai-runtime`, `pi-efficiency`, `validation`, `deployment-readiness`, `distributed-status`, `pi1/2/3-status`, `safety-approvals`, `safety-rejections`, `degraded-mode`, `component-health`, `ai-models`, `speech-ai`, `sarvam`, `perception-ai`, `affective-ai`, `edge-ai-status/models/routes/resources/safety/cache`, `hardware-telemetry`, `navigation-events`, `diagnostics`. `CHANNEL_SNAPSHOTS` computes real, honest (non-fabricated — verified via `test_status_broadcasters.py`'s "honest when missing" assertions) payloads for most of these. This is real, correct backend work with **zero UI consumers** — a dashboard-completeness gap, not a truthfulness bug.
- **FIX_NOW** — `live-logs` (`ws_manager.py:40`, documented at `ws_router.py:10` as "raw log stream, engineer+ only"): grepped for any `_emit("live-logs", ...)` call anywhere — **none exists**. A client that subscribes to this channel and is granted permission will wait forever and receive nothing. Either wire a real log-stream producer or remove the channel from `VALID_CHANNELS` — advertising a capability that silently does nothing is itself a small truthfulness issue.
- `robot-status` — the one channel actually watched — KEEP.

`bonbon_patient_kiosk` has no WebSocket module at all — N/A.

## Broken frontend routes

- `bonbon_patient_kiosk/frontend` — all 14 routes resolve to real, substantial components. No broken routes.
- `bonbon_operator_api/frontend` — no React Router dependency at all (single monolithic `App.tsx`); the empty `components/`/`hooks/`/`pages/` scaffolding directories are a structural finding, not a "broken route" (see `INCOMPLETE_SKELETON_REPORT.md`).

## Dashboard-truthfulness bugs found (2) — cross-referenced, fixed in Phase 9

`restart_module` and `set_config` unconditionally claim success even when the underlying (documented, honest-at-the-bridge-layer) not-implemented call fails. Full detail in `BROKEN_CODE_REPORT.md` items 1-2 — not re-duplicated here. The bridge layer (`ros2_bridge.py`) and the audit log are honest for all of `emergency_stop`, `pause`, `resume`, `restart_module`, `get_config`, `set_config`, `memory_query`, `rag_query` — every one correctly returns `{"success": False, "error": "NOT_IMPLEMENTED"}` internally. But at the **HTTP response layer**, only `restart_module` and `set_config` fail to propagate that honestly (confirmed by direct code read); `emergency_stop`, `pause`, `resume`, `memory_query`, `rag_query` correctly turn the bridge's `success: False` into an HTTP 503 via `command_api.py`'s `_check_bridge_result` pattern. `get_config`'s HTTP-layer behavior was not directly re-verified in this pass and should be checked in Phase 9 rather than assumed either way.
