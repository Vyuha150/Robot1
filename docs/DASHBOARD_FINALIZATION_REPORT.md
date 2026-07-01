# Dashboard Finalization Report

Every card and endpoint the finalization brief's Phase 6 requires, what it
reads, and what it honestly reports when the underlying data doesn't
exist yet.

## The 11 required cards — status

| # | Card | Backed by | Status |
|---|---|---|---|
| 1 | Boot Topology | `GET /deployment/boot-topology`, `/ws/boot-topology` | **PASS** — real `boot_topology.json` |
| 2 | Safety Supervisor Singleton Status | same endpoint's `observed_safety_supervisors`/`duplicate_safety_detected` fields | **PASS** |
| 3 | Raspberry Pi System Status | `GET /robot/status/performance`, `/pi/efficiency` | **PASS** — live CPU/mem/temp when connected |
| 4 | AI HAT / Hailo Runtime Status | `GET /ai-runtime/status`, `/ws/ai-runtime` | **PASS** — live `RuntimeSelector`, honest fallback |
| 5 | Pi Efficiency / Degraded Mode | `GET /pi/efficiency`, `/pi/degraded-mode`, `/ws/pi-efficiency` | **PASS** |
| 6 | Module Health | `GET /diagnostics/modules` ("Live Module Status" panel) | **PASS** — pre-existing, re-verified |
| 7 | Production Scenario Test Status | `GET /validation/test-results`, `/validation/generated-scenarios`, `/ws/validation` | **PASS** — real JUnit XML |
| 8 | Safety Validation Status | `GET /validation/production-score`'s safety category + `/deployment/duplicate-node-check` | **PASS** |
| 9 | Performance Metrics | `GET /robot/status/performance` ("Project Status" panel) | **PASS** — pre-existing |
| 10 | Known Issues | `GET /diagnostics/known-issues`, `GET /deployment/known-issues` (new alias) | **PASS** |
| 11 | Deployment Readiness Score | `GET /diagnostics/deployment-readiness`, `GET /deployment/readiness` (new alias), `GET /dashboard/summary` (new rollup), `/ws/deployment-readiness` | **PASS** |

Frontend: "Project Status", "Raspberry Pi Deployment", and "Behavior
Validation Framework" panels (System tab) collectively surface all 11 —
verified in a live browser in earlier sessions; this pass added no new
frontend panels, only backend endpoints/channels the existing generic
JSON-viewer panels already know how to render.

## The 11 required REST endpoints — status

All 11 exist and return real data or an honest `available: false`:
`/deployment/boot-topology`, `/deployment/duplicate-node-check`,
`/ai-runtime/status`, `/pi/efficiency`, `/pi/degraded-mode`,
`/validation/scenario-families`, `/validation/test-results`,
`/validation/production-score`, `/deployment/known-issues` (**new**,
alias of `/diagnostics/known-issues`), `/deployment/readiness` (**new**,
alias of `/diagnostics/deployment-readiness`), `/dashboard/summary`
(**new**, one-call rollup). 41 backend tests cover the new/aliased
endpoints; the pre-existing ones were already covered.

## The 5 required WebSocket channels — status

`/ws/boot-topology`, `/ws/ai-runtime`, `/ws/pi-efficiency`,
`/ws/validation`, `/ws/deployment-readiness` — **all implemented**,
broadcasting every 5 seconds via a new background task
(`_finalization_status_broadcaster` in `main.py`), reusing the existing
`/ws/{channel}` connection/auth/permission infrastructure (no new WS
mechanism, no duplicate pipeline). Each channel's snapshot builder
(`websocket/status_broadcasters.py`) reads the exact same real source its
REST counterpart reads. 1 connect-level test + 8 snapshot-builder unit
tests.

## No fake green status — how it's enforced

Every endpoint added or aliased in this pass follows the pre-existing
pattern: read a real file/store/live calculator, and if it's missing,
return `{"available": false, "message": "<exact command to fix it>"}`
rather than inventing plausible-looking data. `/dashboard/summary` is a
rollup of those same honest fields, not a new data path — a missing boot
topology file makes `boot_topology_valid: null` in the summary too, it
doesn't get papered over into a fake `true`.

## Tests

199 passed in `bonbon_operator_api`'s full suite (up from 182 before this
pass), 0 failed. New/changed: `test_status_broadcasters.py` (8),
`test_deployment_api.py` (+4 for the aliases), `test_validation_api.py`
(+6 for `/dashboard/summary` and the new WS channels).
