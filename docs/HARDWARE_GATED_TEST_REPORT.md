# Hardware-Gated Test Report (Phase 7)

How BonBon's Pi/Hailo tests behave by environment — the rule is **never fake
a hardware PASS**.

## Behaviour matrix

| Environment | On-device Hailo tests | No-fake-PASS tests | CPU/mock tests |
|---|---|---|---|
| Dev / CI (no Pi, no Hailo) | **SKIP** with reason | run + pass | run + pass |
| Pi without Hailo | SKIP (device-absent reason) | run + pass | CPU fallback runs |
| Pi with Hailo (`BONBON_HAILO_HW_TEST=1`) | **run for real** | skipped (covered on-device) | run |

Gating uses the **real** `HailoDeviceDetector` (no mock), so the skip reason
reflects the actual machine. SKIP ≠ PASS ≠ FAIL — a skipped on-device test is
reported as BLOCKED in the checklist, never green.

## The 16 required tests — where each lives

| # | Test | Location | Status here |
|---|---|---|---|
| 1 | boot_topology_monolithic_valid | `devops/tests/test_boot_topology.py::test_monolithic_mode_valid` | PASS |
| 2 | boot_topology_modular_valid | `…::test_modular_pi_mode_valid` | PASS |
| 3 | boot_topology_mixed_invalid | `…::test_mixed_mode_invalid` | PASS |
| 4 | duplicate_safety_supervisor_detection | `…::test_duplicate_safety_service_fails` + runtime-count override | PASS |
| 5 | hailo_device_detection_mocked | `bonbon_ai_runtime/…::TestHailoDeviceDetector` (4 tests) | PASS |
| 6 | hailo_runtime_unavailable_fallback | `…::test_unavailable_without_hardware` + `test_pi_efficiency_scenarios::test_hailo_unavailable_activates_fallback` | PASS |
| 7 | hailo_model_path_validation | `…::test_hef_path_validation_rejects_wrong_extension` | PASS |
| 8 | runtime_selector_prefers_hailo_when_available | `…::test_prefers_hailo_when_available` | PASS |
| 9 | runtime_selector_falls_back_to_cpu | `…::test_falls_back_to_cpu_when_hailo_absent` | PASS |
| 10 | pi_efficiency_profile_loads | `bonbon_perception_efficiency/…::test_profile_loads_and_validates` | PASS |
| 11 | thermal_degraded_mode_policy | `…::test_thermal_warning_reduces_fps` | PASS |
| 12 | cpu_overload_policy | `…::test_cpu_overload_triggers_degraded_mode` | PASS |
| 13 | dashboard_boot_topology_endpoint | `bonbon_operator_api/tests/test_deployment_api.py` (3 tests) | PASS |
| 14 | dashboard_ai_runtime_endpoint | `…::test_ai_runtime_status_is_honest` + benchmark | PASS |
| 15 | known_issues_contains_real_blockers | `test_project_status.py::test_known_issues_contains_the_real_pi_blockers` | PASS |
| 16 | no_fake_pass_for_hardware_blocked_items | `bonbon_ai_runtime/tests/test_hardware_gated.py` (3 tests) | PASS (+ 3 SKIP) |

## On-Pi run command

```bash
# opt in + point at a real HEF; on a Pi+HAT the SKIPs become real runs
BONBON_HAILO_HW_TEST=1 \
BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
  python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v
```

## This-environment result

`bonbon_ai_runtime`: **30 passed, 3 skipped** (the 3 on-device tests, with
"BLOCKED — run on a Pi 5 + AI HAT" reasons). The 3 no-fake-PASS guards pass,
proving the runtime reports Hailo unavailable and the benchmark CLI exits
non-zero on a silent mock fallback — the dashboard/benchmark cannot show a
Hailo PASS that isn't real.
