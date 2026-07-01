# Three-Pi Current Architecture Audit (Phase 1 — read-only)

**Date:** 2026-07-01
**Scope:** Component-by-component audit of the repo against the planned
three-Raspberry-Pi split (PI-1 UI/API, PI-2 Human AI, PI-3 Navigation/Motion/
Safety). **No code was modified to produce this report.**

This document is the detailed narrative audit. See
[`COMPONENT_SUPPORT_MATRIX.md`](COMPONENT_SUPPORT_MATRIX.md) for the condensed
table, [`HARDWARE_SOFTWARE_GAP_REPORT.md`](HARDWARE_SOFTWARE_GAP_REPORT.md) for
what needs to be built, [`DISTRIBUTED_DEPLOYMENT_BLOCKERS.md`](DISTRIBUTED_DEPLOYMENT_BLOCKERS.md)
for what stops a 3-Pi deployment today, and
[`DUPLICATE_PIPELINE_RISK_REPORT.md`](DUPLICATE_PIPELINE_RISK_REPORT.md) for the
new distributed duplication risks.

## Headline finding

The repo was built and hardened as a **single-machine** system (with a
"monolithic vs. modular-Pi" deployment toggle that still means *one*
Raspberry Pi — see `docs/BOOT_TOPOLOGY.md`). It has never been split across
physically separate machines. Software-wise, the role boundaries the 3-Pi
brief wants (UI/API only on Pi-1, perception/LLM/audio only on Pi-2,
navigation/motors/safety only on Pi-3) already line up cleanly with existing
package boundaries — `bonbon_operator_api` never imports perception/nav
code, the LLM/dashboard cannot reach motor topics, and there is exactly one
safety supervisor. What's missing is (a) two physical actuators for Pi-3, and
(b) every piece of *networking* plumbing needed to run ROS2 across three
machines instead of one.

---

## PI-1 — System UI / API / Dashboard

**Verdict: 7 PASS, 1 PARTIAL. No MISSING items.** The planned PI-1 role is
essentially already built as a self-contained package.

| # | Component | Status | Evidence |
|---|---|---|---|
| 1 | Dashboard backend (FastAPI) | PASS | `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/main.py:1-369` — 12 REST routers, 10 WS channels |
| 2 | Dashboard frontend (React/TS/Vite) | PASS | `ros2_ws/src/bonbon_operator_api/frontend/src/{App,main}.tsx` — 11 tabs |
| 3 | 10.1" touchscreen / kiosk mode | PARTIAL | No kiosk-launch script, no fullscreen/touch handlers in frontend |
| 4 | System monitoring (CPU/RAM/disk/temp) | PASS | `robot_status_api.py`, Grafana dashboard JSON, `/ws/pi-efficiency` |
| 5 | Deployment readiness reporting | PASS | `devops/scripts/boot_topology.py`, `/deployment/boot-topology`, `/ws/boot-topology` |
| 6 | Logs/alerts surfacing | PASS | `ws_router.py` channels `live-logs`/`safety-events`/`navigation-events`/`diagnostics`; `audit_logger.py` |
| 7 | Diagnostics (test results, known_issues, health) | PASS | `project_status_api.py:46-80`, `/diagnostics/test-results`, `/diagnostics/known-issues` |
| 8 | Multi-Pi / distributed awareness | PASS (concept), MISSING (execution) | `TopologyMode` enum exists but is single-Pi "monolithic vs modular"; no PI-1/2/3 IP-aware routing |

**Forbidden-dependency check — CLEAN.** `bonbon_operator_api` imports only its
own submodules, ROS2 standard message packages, and `bonbon_msgs`/`bonbon_srvs`
interface packages. It does **not** import `bonbon_perception`, `bonbon_vision`,
`bonbon_llm`, `bonbon_navigation`, `bonbon_actuation`, `bonbon_speech`, or
`bonbon_audio`. The ROS2 bridge is optional and runs in stub mode when
disabled (`ros2_bridge.py:68-69`), so the API server does not require a local
ROS2 graph to boot.

**Gap for Pi-1-only deployment:** none of the 8 items requires code that
belongs on another Pi. The only real gap is kiosk/touchscreen UX, which is a
deployment/OS-config concern (Chromium `--kiosk`, autologin, display
resolution), not a ROS2-architecture one.

---

## PI-2 — ASR / LLM / Face Recognition / Human Interaction

**Verdict: 10 PASS, 5 PARTIAL, 1 FAIL (hardware driver). No duplicate camera/
mic pipeline risk.**

| # | Component | Status | Evidence |
|---|---|---|---|
| 1 | ReSpeaker XVF3800 4-mic driver | PASS | `bonbon_hal/drivers/microphone/respeaker_driver.py:49` — DOA via USB HID, 16kHz mono ASR output |
| 2 | OAK-D Lite camera | **FAIL** | No depthai/OAK-D/Luxonis driver anywhere; only Orbbec + generic USB/V4L2 exist (`bonbon_hal/drivers/camera/`) |
| 3 | Speaker output (4Ω 10W + PAM8610) | PARTIAL | `alsa_speaker_driver.py:45` works via generic ALSA; no PAM8610-specific gain/power control |
| 4 | ASR (speech-to-text) | PASS | `bonbon_speech/stt/whisper_stt.py:36` — Whisper/faster-whisper, confidence scoring |
| 5 | VAD | PASS | `bonbon_speech/vad/silero_vad.py:38` — 4-state hysteresis FSM + DOA tracking |
| 6 | Local Ollama LLM gateway | PARTIAL | `bonbon_llm/core/ollama_client.py:54` — local-only (no cloud fallback, verified), but default model is `llama3.2:3b`, not the required `qwen2.5:0.5b` — config override needed, not new code |
| 7 | Local RAG | PASS | `bonbon_data_stores/rag/*`, ChromaDB + `all-MiniLM-L6-v2` (~95MB RAM) |
| 8 | Face recognition (identity) | PARTIAL | `bonbon_vision/face/face_pipeline.py` real (opencv_dnn/insightface/deepface backends), but the standalone `face_node.py` is **explicitly quarantined** (orphaned duplicate, disabled in bringup); recognition runs inline in `vision_node`; no dashboard-queryable identity endpoint |
| 9 | Multi-person tracking | PASS | See `docs/PERCEPTION_AI_CURRENT_AUDIT.md` — 53/53 tests |
| 10 | Object intelligence | PARTIAL | Fixed this session (Phase 2 of Perception AI brief, commit `7edf8d1`) — Hailo/CPU runtime wiring + honest class registry now exist |
| 11 | Gesture intelligence | PARTIAL | 12/16 gesture types; see `GESTURE_RECOGNITION_FAILURE_ANALYSIS.md` |
| 12 | Affective AI (emotion) | PARTIAL | Voice emotion stored under global `"_global"` key, not per-person; see `MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md` |
| 13 | Human state fusion | PASS | 73/73 tests, all 18 fields wired |
| 14 | TTS | PASS | `bonbon_tts/backends/piper_tts.py` — local Piper TTS, CPU-based, mock fallback |
| 15 | Duplicate camera/mic pipeline check | PASS (clean) | Exactly one device-opening node each: `bonbon_hal/camera_node`, `bonbon_hal/microphone_node`, `bonbon_hal/speaker_node`. All AI packages subscribe to topics, never open devices directly. `demo_webcam.py` exists but is not in bringup. |

**Gap for Pi-2-only deployment:** the OAK-D Lite driver is a real, unstarted
piece of work (item 2). Everything else is either done or a config/wiring fix
already tracked by the Perception AI brief (items 6, 8, 10-12).

---

## PI-3 — Autonomous Navigation / Motion / Safety

**Verdict: 6 PASS, 2 PARTIAL, 4 MISSING. The 4 MISSING items are the single
largest blocker to any physical 3-Pi deployment — Pi-3 cannot currently move
the robot's base at all.**

| # | Component | Status | Evidence |
|---|---|---|---|
| 1 | RPLiDAR A2M12 | PASS | `bonbon_hal/drivers/lidar/rplidar_driver.py:1-60`, publishes `/bonbon/lidar/scan` |
| 2 | Cytron SmartDrive MDDS30 | **MISSING** | Zero matches anywhere in repo for "cytron"/"mdds30" |
| 3 | Rhino 24V drive motors (base) | **MISSING** | No wheel/base motor controller node exists at all; `/cmd_vel` is published by the safety gate but nothing consumes it |
| 4 | NEMA 17 closed-loop steppers | **MISSING** | Zero matches anywhere in repo for "nema"/"stepper" |
| 5 | 25kgcm digital servos (head/arm) | PASS (compatible, not exact part) | `bonbon_hal/drivers/servo/dynamixel_driver.py` — Dynamixel XL-series, Protocol 2.0, 4 servo IDs (1=neck, 2-4=arm) |
| 6 | Navigation stack | PASS | Real Nav2 (`bonbon_navigation/launch/navigation.launch.py:1-80`) — amcl, planner_server, controller_server, bt_navigator, not a stub |
| 7 | Safety Supervisor | PASS (singleton), PARTIAL (inputs) | Exactly one `safety_supervisor_node` (`bonbon_safety/nodes/safety_supervisor_node.py:104-152`); does **not** yet subscribe to `/bonbon/gesture/events` or `/bonbon/human/state` (confirms prior perception-audit finding, still true) |
| 8 | E-stop | PASS | Hardware GPIO path (`gpio_estop_driver.py`) + software (`estop_node.py`), independent relay-cut path |
| 9 | Degraded motion mode | PARTIAL | `bonbon_perception_efficiency_node.py` implements *perception* load-shedding on thermal pressure; there is no separate "degraded **motion**" mode distinct from the existing CAUTION/DOCKING velocity caps in the safety gate |
| 10 | Motion command authority chain | PASS (verified clean) | Traced LLM → dashboard → navigation → safety_gate_node; **only** `safety_gate_node.py:14-58` publishes to final `/cmd_vel` and `/bonbon/servo/*/command` topics; LLM and dashboard code explicitly cannot reach them |
| 11 | Joint/servo status reporting | PASS | `/bonbon/servo/neck/state`, `/bonbon/servo/arm/state` — full Dynamixel telemetry (position/velocity/load/temp) |
| 12 | Duplicate safety-supervisor risk | PASS (resolved) | Four-layer defense confirmed still intact: systemd `Conflicts=`, `select_deployment_mode.sh`, `boot_topology.py` validator, `check_duplicate_ros_nodes.sh` |

**Gap for Pi-3-only deployment:** items 2-4 are not "wiring gaps," they are
**net-new hardware integration work** — a `bonbon_drive_motors` HAL package
(Cytron MDDS30 PWM/serial driver + Rhino motor control + wheel odometry) does
not exist in any form, and neither does NEMA 17 stepper support. Nav2 has
nothing to actuate. This is the most severe finding in the entire audit —
more severe than any Pi-2 perception gap — because it means the physical
robot cannot drive today regardless of the 3-Pi split.

---

## Cross-cutting distributed-deployment readiness

Covered in depth in `DISTRIBUTED_DEPLOYMENT_BLOCKERS.md`; summary:

- **Zero `ROS_DOMAIN_ID` / DDS network config exists anywhere in the repo.**
  Every launch file, systemd unit, and script assumes default localhost DDS
  discovery.
- **No per-Pi launch files.** `bringup.launch.py` (222 lines) still launches
  the full single-machine stack; per-subsystem launch files exist
  (`safety.launch.py`, `vision.launch.py`, etc.) but were designed for
  systemd modularity on **one** Pi, not physical separation across three.
- **Dashboard bridge hardcodes topic names it assumes are locally reachable**
  (`ros2_bridge.py:73-104`) — this will silently time out across machines
  unless DDS discovery is configured identically on all three Pis.
- **`config/pi_efficiency_profile.yaml` is a single, unscoped priority list**
  assuming all 18 modules run on one machine; it will make wrong
  load-shedding decisions once split (e.g. a Pi-1 profile has nothing
  perception-related to shed).
- **No "distributed" or "PI-1/PI-2/PI-3" concept exists anywhere in the repo**
  today (confirmed via full-repo grep) — this 3-Pi brief is the first time
  the system is being designed for physical multi-machine deployment.

## What is *already* correct and must be preserved, not rebuilt

- Single safety supervisor, enforced by systemd `Conflicts=` + two validator
  scripts (`boot_topology.py`, `check_duplicate_ros_nodes.sh`).
- No duplicate camera/mic device opens — HAL is the sole owner of every
  physical sensor/actuator device handle.
- LLM and dashboard code cannot reach motor/servo/cmd_vel topics under any
  traced code path — the proposal-only pattern the 3-Pi brief asks for
  already exists in spirit for single-machine deployment; it needs to be
  extended across the network boundary, not invented from scratch.
- Local-only LLM (no cloud fallback path exists in `ollama_client.py`).
