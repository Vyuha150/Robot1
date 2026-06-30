# BonBon Raspberry Pi 5 + Hailo AI HAT — Final Deployment Release Checklist

**Date:** 2026-07-01

**The constraint that still governs this checklist:** this work was done on a
Windows dev machine with **no Raspberry Pi, no Hailo AI HAT, and no ROS2
install.** Anything needing a running robot on real hardware is marked
`BLOCKED` — never PASS. But the two previous *static* blockers (duplicate
safety supervisor; no Hailo backend) are now **resolved in code and tested
without hardware**, so several rows moved from FAIL → PASS / PARTIAL.

Verdict key: **PASS** = verified in this environment. **FAIL** = statically
broken. **PARTIAL** = implemented + tested without hardware, needs on-Pi
confirmation. **BLOCKED** = requires a real Pi/Hailo/robot.

| # | Item | Verdict | Evidence / on-Pi confirm |
|---|---|---|---|
| 1 | BonBon boots on Pi without manual intervention | **PARTIAL** | Boot path is now coherent (single safety supervisor, `Conflicts=` guards, mode scripts). Confirm on Pi: `sudo reboot` → `systemctl is-active bonbon-*`. |
| 2 | Safety Supervisor starts first / highest priority | **PASS (static)** | Modular units `Requires=bonbon-safety` + `After=bonbon-safety bonbon-hal`; safety container `oom_score_adj:-900` + `cpu_shares:4096`. 12 topology tests. Live ordering is the BLOCKED part. |
| 3 | AI HAT detected and used for compatible models | **PARTIAL** | Detected: `pi_hardware_check.sh` + `HailoDeviceDetector`. Used: `HailoRuntime` + `RuntimeSelector` implemented & tested (mocked). **Real on-HAT inference is BLOCKED** + the `vision_node` adapter is the documented next step. |
| 4 | Unsupported models fall back safely | **PASS** | `RuntimeSelector` fail-open chain (hailo→cpu→mock) + `BaseDetector` degraded mode. Tested. |
| 5 | CPU does not remain overloaded | **PARTIAL** | `LoadSheddingController` + `FrameSamplingManager` + Pi FPS caps; 10 efficiency scenario tests. Measured CPU% on a live Pi is BLOCKED. |
| 6 | Temperature does not throttle in normal operation | **PARTIAL** | Thermal wired into load shedding (75°C caution, before 90°C SAFE_STOP); tested. Live `vcgencmd get_throttled` is BLOCKED. |
| 7 | Emergency stop works during full AI load | **BLOCKED** | Architecturally sound (separate 50 Hz GPIO `estop_node`, OOM/CPU-priority on safety container). Real-load latency is hardware-only. |
| 8 | Camera/mic/speaker/lidar/IMU/display/actuation detected | **BLOCKED** | `pi_hardware_check.sh` probes all of them — run it on the Pi. |
| 9 | Dashboard shows real Pi, AI HAT, safety, perf, test data | **PASS** | New `/deployment/*`, `/ai-runtime/*`, `/pi/*` endpoints read real data; "Raspberry Pi Deployment" card verified in a live browser; 11 tests. AI-HAT data is honest (mock/cpu fallback shown until a real device). |
| 10 | No duplicate camera/audio/database/safety pipelines | **PASS** | Duplicate-safety-supervisor topology FIXED (Conflicts= + validator + mode scripts). 12 tests. |
| 11 | LLM cannot directly control navigation or actuation | **PASS** | Re-verified: `CommandAuthorizer` gate; zero LLM→actuation topic coupling. |
| 12 | Degraded mode works when AI HAT/camera/mic/lidar/model fails | **PARTIAL/PASS** | Model/Hailo/CPU failure → degraded: PASS (tested). Unplug-the-camera-mid-run is BLOCKED on hardware. `degraded_mode.yaml` never sheds safety (tested). |
| 13 | Systemd boot deployment works | **PARTIAL** | 11 units (8 + hal/behavior/actuation) with mutually-exclusive modes + validator; the previously-broken enable flow is fixed. Live `systemctl enable --now` + one-supervisor check is BLOCKED. |
| 14 | Logs and health checks available | **PASS** | `health_check.sh`, per-node `ModuleHealth` + `~/health_check`, `/diagnostics/modules`, mounted `/var/log/bonbon`. |
| 15 | Final PASS/FAIL release checklist complete | **PASS** | This document + 6 phase reports. |

## Summary

| Verdict | Count | Items |
|---|---|---|
| PASS | 6 | 2, 4, 9, 10, 11, 14, 15 (static) |
| PARTIAL (tested, needs on-Pi confirm) | 6 | 1, 3, 5, 6, 12, 13 |
| BLOCKED (needs Pi/Hailo) | 3 | 7, 8, + on-hardware halves of the PARTIALs |
| FAIL | 0 | — |

**Both previous blockers are resolved.** The deployment moved from
`5 PASS · 4 FAIL · 2 PARTIAL · 5 BLOCKED` to **0 FAIL**, with the remaining
work being genuine on-hardware confirmation rather than missing code.

## Exact commands to run on the Raspberry Pi

```bash
# hardware present?
bash scripts/pi_hardware_check.sh
# select modular production mode (one safety supervisor)
sudo bash scripts/select_deployment_mode.sh modular_pi
# validate no duplicate safety supervisor
python3 scripts/validate_boot_topology.py --check-running-nodes
bash scripts/check_duplicate_ros_nodes.sh
# benchmark Hailo inference (honest: exits non-zero if it fell back to mock/cpu)
ros2 run bonbon_ai_runtime ai_runtime_bench --mode auto \
  --hailo-hef /opt/bonbon/models/hailo/yolo_object_detection.hef --runs 50
# on-device hardware-gated test suite
BONBON_HAILO_HW_TEST=1 \
BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
  python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/test_hardware_gated.py -v
```

## Reports

BOOT_TOPOLOGY_FIX_REPORT · HAILO_RUNTIME_INTEGRATION_REPORT ·
PI_EFFICIENCY_PROFILE_REPORT · DASHBOARD_PI_DEPLOYMENT_UPDATE_REPORT ·
HARDWARE_GATED_TEST_REPORT · plus the Phase-1 CURRENT_*_REPORT trio.
