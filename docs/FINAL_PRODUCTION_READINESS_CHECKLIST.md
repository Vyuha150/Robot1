# Final Production Readiness Checklist

**Date:** 2026-07-01. Verdicts: **PASS** (verified in this environment) ·
**FAIL** (verified and failed) · **PARTIAL** (implemented but incomplete)
· **BLOCKED** (requires actual Pi / AI HAT / ROS2 build / robot hardware).

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Boot topology | **PASS** | `classify_topology()` correctly classifies monolithic/modular_pi as valid and mixed as INVALID; 12 tests. [BOOT_TOPOLOGY.md](BOOT_TOPOLOGY.md) |
| 2 | Duplicate safety prevention | **PASS** | 4-layer guard (systemd `Conflicts=`, mode scripts, static validator, runtime check); `known_issues.json`'s `systemd_duplicate_safety_supervisor` entry corrected to `resolved` this pass. [BOOT_TOPOLOGY_FIX_REPORT.md](BOOT_TOPOLOGY_FIX_REPORT.md) |
| 3 | Hailo runtime abstraction | **PASS** | `VisionModelRuntimeInterface` + 4 implementations + `RuntimeSelector`; 27 unit tests. [AI_HAT_RUNTIME_REPORT.md](AI_HAT_RUNTIME_REPORT.md) |
| 4 | Hailo hardware detection | **PARTIAL** | `HailoDeviceDetector` implemented and tested (real + injected paths); real detection on an actual AI HAT is BLOCKED (row 18 below is the hardware half) |
| 5 | Pi efficiency profile | **PASS** | 17-item frozen priority order (corrected to match [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) exactly this pass); 88 tests. [PI_EFFICIENCY_PROFILE_REPORT.md](PI_EFFICIENCY_PROFILE_REPORT.md) |
| 6 | Degraded mode | **PASS** | `DegradedModeManager` + `config/runtime/degraded_mode.yaml`; safety-critical modules never shed (validated by `PiEfficiencyProfile.validate()` + tests) |
| 7 | Dashboard readiness | **PASS** | 11 cards, 11 REST endpoints (`/deployment/known-issues`, `/deployment/readiness`, `/dashboard/summary` new this pass), 5 new WS channels; 199 tests. [DASHBOARD_FINALIZATION_REPORT.md](DASHBOARD_FINALIZATION_REPORT.md) |
| 8 | Production scenario framework | **PASS** | 15 families, 459 generated scenarios, 655 production tests. [PRODUCTION_BEHAVIOR_VALIDATION_REPORT.md](PRODUCTION_BEHAVIOR_VALIDATION_REPORT.md) |
| 9 | Behavior Oracle | **PASS** | All 8 required checks implemented (of 10 total); 14 unit tests. [BEHAVIOR_ORACLE.md](BEHAVIOR_ORACLE.md) |
| 10 | Safety validation | **PASS** | `bonbon_safety` pure-Python suite (198 tests) + `SafetyPolicy` real-config checks + production safety/behavior-engine scenarios (79 passed, 1 skipped) |
| 11 | LLM action blocking | **PASS** | Zero `BehaviorDecision`/`ActuationGesture` construction outside `bonbon_behavior_engine` (re-confirmed by grep); `CommandAuthorizer` gates every LLM-resolved behavior; oracle check on every scenario run |
| 12 | No duplicate pipelines | **PASS** | Boot-topology guard is the structural enforcement; re-verified no new camera/audio/database/safety pipeline was introduced this pass |
| 13 | Config validation | **PASS** | `python scripts/validate_config.py --all` — 5/5 environments |
| 14 | Test execution | **PASS** | See [TEST_EXECUTION_REPORT.md](TEST_EXECUTION_REPORT.md) — every runnable category passed, 0 failures |
| 15 | Systemd deployment | **PARTIAL** | Units + `Conflicts=` + mode scripts written and unit-tested; live `systemctl enable/start` on a real Pi is BLOCKED (row 16) |
| 16 | Raspberry Pi commands | **BLOCKED** | No physical Pi in this environment; exact commands documented and ready to run (see below) |
| 17 | AI HAT benchmark commands | **BLOCKED** | No physical AI HAT in this environment; `ai_runtime_bench` CLI implemented and unit-tested against mocks, real benchmark command documented below |
| 18 | Emergency stop under load | **BLOCKED** | Requires physical GPIO e-stop + concurrent full AI load on real hardware; `test_real_estop_latency_under_full_ai_load` SKIPs honestly |
| 19 | Thermal test | **BLOCKED** | Requires physical Pi under sustained load; `test_real_cpu_temperature_stability_under_load` SKIPs honestly |
| 20 | Final release decision | **PARTIAL** | See verdict below — release candidate, not a final production sign-off, pending the 4 BLOCKED hardware items |

## Count

**13 PASS · 0 FAIL · 3 PARTIAL (4, 15, 20) · 4 BLOCKED (16, 17, 18, 19)**

## Final verdict

**RELEASE CANDIDATE.** Every blocker resolvable without physical hardware
is resolved and tested. Zero FAILs. The remaining PARTIAL/BLOCKED items
are exactly and only the ones that require a real Raspberry Pi 5 + AI HAT
+ physical robot — none are hidden, none are marked PASS without
evidence. Full narrative: [FINAL_RELEASE_CANDIDATE_REPORT.md](FINAL_RELEASE_CANDIDATE_REPORT.md).

## Blockers fixed

1. Duplicate safety supervisor / invalid boot topology.
2. No confirmed Hailo / AI HAT runtime integration (abstraction layer;
   live vision-node wiring is a documented POST-RELEASE follow-up, not a
   blocker to this abstraction being real and tested).

## Blockers remaining (all hardware-only)

3. Raspberry Pi performance/thermal risk — mitigated in software, not yet
   measured on real hardware.
4. Live confirmation of items 15-19 above.

## Exact commands

```bash
# 5. exact commands to run on Raspberry Pi
bash scripts/pi_hardware_check.sh
sudo cp deployment/systemd/bonbon-*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 6. select modular Pi mode
sudo bash scripts/select_deployment_mode.sh modular_pi

# 7. validate duplicate safety supervisor is absent
python3 scripts/validate_boot_topology.py --check-running-nodes
bash scripts/check_duplicate_ros_nodes.sh

# 8. test Hailo detection
bash scripts/pi_hardware_check.sh   # AI HAT / Hailo section
BONBON_HAILO_HW_TEST=1 python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v

# 9. run production scenario tests
bash scripts/run_production_tests.sh
BONBON_HAILO_HW_TEST=1 BONBON_PI_HW_TEST=1 bash scripts/run_production_tests.sh --all

# 10. start the dashboard
uvicorn bonbon_operator_api.main:_build_app --factory --host 0.0.0.0 --port 8080
cd ros2_ws/src/bonbon_operator_api/frontend && npm run dev

# AI HAT benchmark
ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
```

## What should be physically tested next

1. Boot both deployment modes on a real Pi 5; confirm exactly one
   `safety_supervisor_node` via `ros2 node list`.
2. Run the Hailo hardware-gated suite with a real AI HAT + compiled
   `.hef` model; confirm `selected_kind == hailo` and
   `fallback_active == False`.
3. Measure e-stop latency under full concurrent AI load
   (`BONBON_ESTOP_LATENCY_LOG`); confirm ≤ 500ms.
4. Measure sustained CPU%/temperature against the efficiency profile's
   thresholds (`BONBON_THERMAL_LOG`); confirm shedding triggers before
   `cpu_temp_fault_c`.
5. Physically unplug a sensor mid-run; confirm degraded mode enters and
   recovers correctly.
6. Once 1-5 pass, run the full multi-person/gesture/speech accuracy
   suite in a real room against real people.
