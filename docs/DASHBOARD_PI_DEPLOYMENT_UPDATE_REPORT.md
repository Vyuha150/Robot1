# Dashboard Pi Deployment Update Report (Phase 6)

Made the two Pi blockers measurable and actionable from the operator
dashboard — all reading **real** backend data, none hardcoding PASS.

## New endpoints (`bonbon_operator_api/api/deployment_api.py`)

| Endpoint | Source | Honest-fallback |
|---|---|---|
| `GET /deployment/boot-topology` | `devops/project-status/boot_topology.json` (written by `validate_boot_topology.py`) | `available:false` + "run the validator" if missing |
| `GET /deployment/duplicate-node-check` | the verdict's observed safety-supervisor count | points at `check_duplicate_ros_nodes.sh` |
| `POST /deployment/select-mode` | returns the exact host command | does NOT run `sudo systemctl` (privileged host action; `config:write:critical`) |
| `GET /ai-runtime/status` | **live `RuntimeSelector`** | reports mock/cpu fallback + reason; never a fake Hailo PASS |
| `GET /ai-runtime/models` | `config/runtime/model_runtime.yaml` | `available:false` if absent |
| `GET /ai-runtime/benchmark` | live benchmark of the selected runtime | carries `is_real_accelerator` so mock ≠ Hailo |
| `GET /pi/efficiency` | `config/pi_efficiency_profile.yaml` + live perf snapshot | live CPU/mem/temp always included |
| `GET /pi/degraded-mode` | `config/runtime/degraded_mode.yaml` + live degraded flag | shows shed_order / never_disable |

(`/diagnostics/deployment-readiness` and `/diagnostics/known-issues` already
existed from the earlier dashboard work and surface the two Pi blockers via
`devops/project-status/known_issues.json`.)

## Frontend

7 new `api.ts` client methods + a **"Raspberry Pi Deployment"** panel in the
System tab (5 buttons: boot topology / AI runtime / AI benchmark / Pi
efficiency / degraded mode), structurally identical to the verified
"Project Status" panel. **Verified in a live browser** via the preview
tools: `tsc --noEmit` clean (exit 0), app renders with no console errors,
the new panel is present with all 5 buttons, correctly positioned between
"Project Status" and "Live Module Status".

## No fake PASS — by construction

The AI-runtime endpoints run the actual `RuntimeSelector`. On this
no-accelerator machine they return `selected_kind: mock`,
`fallback_active: true`, `is_real_accelerator: false` — the dashboard
physically cannot show a Hailo PASS that isn't real. 11 endpoint tests
assert exactly this, plus the boot-topology present/missing paths,
select-mode command generation/rejection, live-perf inclusion,
safety-never-in-shed-order, and auth-required.

## WebSockets (honest scope)

The four `/ws/...` streaming channels in the brief were **not** added; the
REST endpoints (the must-have "real backend data, no fake PASS" deliverable)
are complete and tested. The existing dashboard already has a websocket
layer (`ws_router`) these would extend — a follow-up, not a blocker, since
the data is fully available via REST today.
