# BonBon Raspberry Pi 5 + Hailo AI HAT — Final Deployment Release Checklist

**Date:** 2026-06-30

**The one constraint that governs this entire checklist:** this verification
was run on a Windows development machine with **no Raspberry Pi, no Hailo AI
HAT, no Hailo hardware, and no ROS2 install.** Any item whose confirmation
requires observing a running robot on real hardware **cannot be confirmed
here, and is marked `BLOCKED` — not PASS.** Marking such an item PASS would
be fabricating a hardware result I did not obtain. For every BLOCKED item the
exact on-Pi command/observation that would confirm it is given, so the check
is completable the moment the hardware is in hand.

Verdict key: **PASS** = statically verified true in code/config. **FAIL** =
statically verified false/missing. **PARTIAL** = some sub-parts pass, others
fail/blocked. **BLOCKED** = correct only on real hardware; cannot be judged
from here.

| # | Item | Verdict | Evidence / how to confirm on the Pi |
|---|---|---|---|
| 1 | BonBon boots on Pi without manual intervention | **BLOCKED** | The mechanism exists (8 systemd units, `WantedBy=multi-user.target`, `restart: unless-stopped` on every compose service). But see item 13 — the documented boot is currently **broken** by the duplicate-service topology (item 2/10). Confirm after fixing that: `sudo reboot`, then `systemctl is-active bonbon-*` all `active`. |
| 2 | Safety Supervisor starts first / highest runtime priority | **FAIL** | Two real defects, both static: (a) `bonbon-core` (full `bringup.launch.py`) has **no** `After=`/`Requires=bonbon-safety`, and `bonbon-perception`/`bonbon-speech`/`bonbon-dashboard` only wait for `bonbon-core`, not safety — so safety is **not** guaranteed first. (b) No service had OS/container priority protection. **Partially fixed this pass:** the safety container now has `oom_score_adj: -900` + `cpu_shares: 4096` (kernel kills it last, scheduled above AI under contention). The ordering defect is entangled with item 2/10's duplication and was left for hardware-validated resolution. |
| 3 | AI HAT detected and used for compatible vision models | **FAIL** | **Detected:** yes — `pi_hardware_check.sh` now probes `lspci \| grep hailo` and `hailortcli fw-control identify`. **Used:** no — zero Hailo references in 736 Python files; `yolo_detector.py` has no HailoRT (`.hef`) path, so inference runs on the ARM CPU. A `HailoDetector(BaseDetector)` backend must be built (logged in known-issues). |
| 4 | Unsupported models fall back safely | **PASS** | `base_detector.py` implements degraded mode (`_is_degraded`, returns empty `DetectionResult` and skips inference); `yolo_detector.load_model()` calls `_enter_degraded()` on missing model / missing ultralytics / load exception. Verified by reading the code and the existing `bonbon_vision` degraded-mode tests. |
| 5 | CPU does not remain overloaded | **BLOCKED** | Mechanism present and unit-tested: `ResourceMonitor` → `/bonbon/system/resource_usage` → `LoadSheddingController` (escalate immediately, de-escalate with hysteresis) + `FrameSamplingManager`. Whether it *keeps CPU below saturation in practice* is a runtime property. Confirm on Pi under load: `vcgencmd measure_clock arm`, `top`, and watch `/bonbon/perception_efficiency/budget` shed load. |
| 6 | Temperature does not throttle during normal operation | **BLOCKED** | Mechanism present: thermal wired into `LoadSheddingController` this engagement (`cpu_temp_caution_c=75`, mirrors `bonbon_safety`'s own caution threshold, sheds load before the supervisor's 90°C SAFE_STOP). Runtime-only to confirm: on the Pi, `watch -n1 vcgencmd measure_temp` and `vcgencmd get_throttled` (must stay `0x0`) through a normal session. |
| 7 | Emergency stop works during full AI load | **BLOCKED (partial static support)** | Architecturally sound: `estop_node` is a **separate** 50 Hz GPIO-poller process/executable (not inside any AI node), and the safety container now has OOM + CPU-priority protection (item 2). But "works under full load" is a hardware real-time property — confirm on Pi: saturate all cores, press the physical e-stop, measure latency to motor cut. Full guarantee would also want `cpuset` core isolation (documented in the compose comment, deferred to hardware validation). |
| 8 | Camera, mic, speaker, lidar, IMU, display, actuation detected | **BLOCKED** | `scripts/pi_hardware_check.sh` (extended this engagement) probes every one of these and prints PASS/WARN/FAIL. Run it on the Pi: `bash scripts/pi_hardware_check.sh`. It is the authoritative answer for this item and cannot be answered from a non-Pi machine. |
| 9 | Dashboard shows real Pi, AI HAT, safety, performance, test data | **PARTIAL** | **PASS:** safety (`/robot/status/safety`), performance (`/robot/status/performance` — real `ResourceUsage`+`PerceptionEfficiencyMetrics`), test data (`/diagnostics/test-results`), known issues incl. these Pi findings (`/diagnostics/known-issues`) — all wired and tested this engagement. **MISSING:** no Pi-hardware card (the `pi_hardware_check.sh` output isn't exposed via the API), and **no AI-HAT/NPU telemetry source exists at all** (item 3), so the dashboard cannot show AI HAT data. |
| 10 | No duplicate camera/audio/database/safety pipelines | **FAIL** | **In the ROS2 graph: PASS** (re-verified — single safety supervisor, single vision/audio/db owner). **In the documented systemd deployment: FAIL** — enabling `bonbon-core` (full bringup) alongside `bonbon-safety`/`bonbon-perception`/`bonbon-speech`/`bonbon-tts`/`bonbon-navigation`, exactly as `systemd_setup.md` instructs, runs each of those **twice** (duplicate node names, duplicate `/bonbon/safety/state` publishers). This is the top blocker; documented in known-issues, not fixed (re-architecting the safety boot topology needs hardware validation). |
| 11 | LLM cannot directly control navigation or actuation | **PASS** | Re-verified: `llm_orchestrator_node` routes every behavior through `CommandAuthorizer.authorize()` against live `SafetyState`; zero topic overlap between `bonbon_llm` publications and `bonbon_actuation`/`bonbon_navigation` subscriptions (the one shared topic, `/bonbon/safety/state`, is a read-only safety-state subscription). |
| 12 | Degraded mode works when AI HAT / camera / mic / lidar / model fails | **PARTIAL (PASS for the testable paths)** | Model/detector failure → degraded mode: PASS (item 4, tested). Camera/mic/lidar driver failure → HAL drivers and downstream nodes have degraded handling (verified by code inspection). AI HAT failure: N/A today (no Hailo path exists, item 3) — once a `HailoDetector` is built it must `_enter_degraded()` → CPU fallback on Hailo init failure, which the `BaseDetector` interface already supports. End-to-end "unplug the camera mid-run" is BLOCKED on hardware. |
| 13 | Systemd boot deployment works | **FAIL** | 8 well-formed units exist with a documented install/enable flow — but the flow as documented produces the item 2/10 duplication. The units *load and start* fine; the *resulting system* is wrong. Confirm after the topology fix: `systemctl enable --now bonbon-<...>`, then verify exactly one `safety_supervisor_node` via `ros2 node list`. |
| 14 | Logs and health checks available | **PASS** | `devops/scripts/health_check.sh`, `pre_deploy_check.py`, `post_deploy_check.py` all present; every node publishes `ModuleHealth` + offers a `~/health_check` service; the dashboard exposes `/diagnostics/modules` and `/robot/status/health`; compose mounts `/var/log/bonbon` into every container. Verified by inspection. |
| 15 | Final PASS/FAIL release checklist complete | **PASS** | This document. |

## Summary

| Verdict | Count | Items |
|---|---|---|
| PASS | 5 | 4, 11, 14, 15, + #10's ROS2-graph half |
| FAIL | 4 | 2, 3, 10 (systemd half), 13 |
| PARTIAL | 2 | 9, 12 |
| BLOCKED (needs Pi hardware) | 5 | 1, 5, 6, 7, 8 |

## The two blocking findings to resolve before a Pi deployment

1. **Duplicate safety supervisor in the documented systemd setup** (items 2, 10, 13). `bonbon-core` runs the whole stack while granular per-subsystem services run the same subsystems again; the docs tell you to enable both. Re-architect so the safety supervisor (and perception/audio/nav) start exactly once — validate on the real 4-core Pi 5 before shipping, since it changes how the safety-critical container boots.

2. **No Hailo AI HAT acceleration** (items 3, 9). The vision stack was scoped for NVIDIA Jetson; there is no HailoRT backend, so vision inference runs on the Pi CPU. Build a `HailoDetector(BaseDetector)` (the interface already supports the CPU-fallback-on-failure contract degraded mode needs) and add NPU telemetry so the dashboard can show AI-HAT data.

## What was actually fixed in this pass (safe, hardware-independent)

- Hardened the safety container's runtime priority (`oom_score_adj: -900`, `cpu_shares: 4096`) — correct under any resolution of the topology question, directly serving requirements #2/#3.
- Extended `scripts/pi_hardware_check.sh` to detect all 21 Phase-1 hardware/OS/Hailo items (prior pass).
- Surfaced both blocking findings on the dashboard via `devops/project-status/known_issues.json`.

## What was deliberately NOT done, and why

The duplicate-safety-supervisor re-architecture and the Hailo detector backend were **not** implemented. Both touch safety-critical / accelerator paths that cannot be tested without the actual Pi 5 + AI HAT, and shipping an unverified change to how the safety supervisor boots — or to the inference path — would be less safe than shipping a clearly-documented known blocker. This is the same engineering discipline applied throughout this engagement: do not pass off untested changes to safety-critical paths as done.
