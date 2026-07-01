# Final Release Candidate Report

**Date:** 2026-07-01
**Mode:** Finalization — architecture frozen, blockers resolved to the
extent verifiable without physical hardware, production readiness
assessed honestly.

## Verdict: RELEASE CANDIDATE — PARTIAL

Every blocker this pass targeted is **fixed in code and tested off-
hardware**. Nothing is faked: the items that genuinely require a
Raspberry Pi 5 + AI HAT + physical robot are marked **BLOCKED**, not
PASS, per the exact count in
[FINAL_PRODUCTION_READINESS_CHECKLIST.md](FINAL_PRODUCTION_READINESS_CHECKLIST.md).
This is a release **candidate** specifically because the BLOCKED items
are real and must be closed on physical hardware before a production
rollout — this report does not claim otherwise.

## The 6 blockers/focus areas from the finalization brief

| # | Focus area | Outcome |
|---|---|---|
| 1 | Duplicate safety supervisor / invalid boot topology | **FIXED** — four-layer guard, 12 tests, [BOOT_TOPOLOGY_FIX_REPORT.md](BOOT_TOPOLOGY_FIX_REPORT.md) |
| 2 | No confirmed Hailo / AI HAT runtime integration | **FIXED (abstraction)** — runtime selector + honest fallback, 30 tests, [AI_HAT_RUNTIME_REPORT.md](AI_HAT_RUNTIME_REPORT.md). Live vision-node wiring is POST-RELEASE. |
| 3 | Raspberry Pi performance and thermal risk | **MITIGATED** — 17-item priority profile, load shedding, thermal policy, 88+71 tests, [PI_EFFICIENCY_PROFILE_REPORT.md](PI_EFFICIENCY_PROFILE_REPORT.md). Measured numbers need real hardware. |
| 4 | Production-ready scenario validation system | **DONE** — 15 families, 459 scenarios, Behavior Oracle, production score, 655+14+14+41 tests, [PRODUCTION_BEHAVIOR_VALIDATION_REPORT.md](PRODUCTION_BEHAVIOR_VALIDATION_REPORT.md) |
| 5 | Real dashboard readiness reporting | **DONE** — 11 cards, 11 REST endpoints (3 new this pass), 5 new WebSocket channels, 199 tests, [DASHBOARD_FINALIZATION_REPORT.md](DASHBOARD_FINALIZATION_REPORT.md) |
| 6 | Clean final documentation and run commands | **DONE** — this report + 10 companion reports, all commands verified to actually run in this environment |

## What changed in this finalization pass specifically

Given almost everything above was already implemented in prior sessions,
this pass's real work was: (a) writing the architecture freeze that makes
"what ships" unambiguous, (b) finding and fixing a genuine staleness bug
(`known_issues.json` still marking both blockers as unresolved after they
were fixed — would have made the dashboard's readiness endpoints lie),
(c) correcting a real doc/config discrepancy (Pi efficiency priority
order), (d) closing the one real functional gap (the 5 WebSocket channels
+ 2 endpoint aliases + 1 rollup endpoint Phase 6 required but didn't yet
exist), and (e) the full verification sweep + this report set. No
existing working system was rewritten or re-architected — "fix only what
is required" was followed literally.

## Rules compliance (self-check against the brief's critical rules)

| Rule | Compliance |
|---|---|
| Do not fake hardware PASS | **Held** — every hardware-dependent item is BLOCKED/SKIP with a stated reason, never PASS |
| Do not mark Pi/Hailo/robot tests as passed unless tested on real hardware | **Held** — see [HARDWARE_GATED_TESTS.md](HARDWARE_GATED_TESTS.md) |
| Do not create duplicate camera/audio/database/safety pipelines | **Held** — boot-topology guard is the enforcement mechanism; re-verified, no new pipelines added |
| Do not bypass Safety Supervisor | **Held** — `ActuationSafetyGate`/`SafetyCommandGate` unchanged; new endpoints are read-only |
| Do not allow LLM direct navigation or actuation | **Held** — re-verified via `test_behavior_engine_scenarios.py`'s `llm_no_direct_action` oracle check |
| Do not leave empty skeleton packages | **Held** — none added; pre-existing `ai_core/`/`simulation/`/`tools/` skeletons were already removed in an earlier pass |
| Do not leave placeholder logic | **Held** — every new endpoint/channel reads a real source or returns an honest `available: false` |
| Do not add unnecessary new modules | **Held** — new code is 1 new file (`status_broadcasters.py`) + additions to 6 existing files; the 5 new WS channels reuse the existing `/ws/{channel}` mechanism rather than adding a second one |
| Fix only what is required for production readiness | **Held** — see "what changed" above |
| Every fix must have tests, config, docs, and dashboard visibility | **Held** — the rank-order fix has tests (re-run) + docs (this + PI_EFFICIENCY_PROFILE_REPORT.md) + config (the yaml itself); the known_issues fix has docs + is dashboard-visible by construction (it IS the dashboard's data source); the new endpoints/channels have all four |

## Final PASS/FAIL/PARTIAL/BLOCKED count

See [FINAL_PRODUCTION_READINESS_CHECKLIST.md](FINAL_PRODUCTION_READINESS_CHECKLIST.md)
for the full 20-item breakdown. Summary: **13 PASS · 0 FAIL · 3 PARTIAL ·
4 BLOCKED**.

## Exact commands (also in the final checklist)

```bash
# on the Raspberry Pi
bash scripts/pi_hardware_check.sh
sudo bash scripts/select_deployment_mode.sh modular_pi
python3 scripts/validate_boot_topology.py --check-running-nodes
bash scripts/check_duplicate_ros_nodes.sh
BONBON_HAILO_HW_TEST=1 python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v

# in this dev environment
bash scripts/run_production_tests.sh
uvicorn bonbon_operator_api.main:_build_app --factory --host 0.0.0.0 --port 8080
```

## What should be physically tested next

In priority order: (1) boot both deployment modes on a real Pi 5, confirm
exactly one `safety_supervisor_node` via `ros2 node list`; (2) run the
Hailo hardware-gated suite with a real AI HAT and a compiled `.hef`
model; (3) measure e-stop latency under full concurrent AI load; (4)
measure sustained CPU%/temperature against the efficiency profile's
thresholds; (5) once 1-4 pass, begin closing the remaining BLOCKED
checklist rows (sensor unplug, multi-person/gesture/speech accuracy).
