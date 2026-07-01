# Component Support Matrix (Three-Pi Split)

**Date:** 2026-07-01
**Scope:** Every component named in the three-Pi brief, one row each, with
support status, current implementation, and exact remaining development.
Companion to `THREE_PI_CURRENT_ARCHITECTURE_AUDIT.md` (narrative version).

Status legend: **PASS** = production-ready as-is · **PARTIAL** = real
implementation with a known gap · **FAIL** = attempted but broken/unsuitable ·
**MISSING** = no implementation exists · **BLOCKED** = cannot verify without
hardware not present in this environment.

## PI-1 — System UI / API / Dashboard (192.168.10.11)

| Component | Status | Package/Node | Driver/Lib | Topics/Endpoints | Dashboard Visibility | Test Coverage | Failure Mode | Recovery | Dev Needed |
|---|---|---|---|---|---|---|---|---|---|
| Dashboard backend (FastAPI) | PASS | `bonbon_operator_api` | fastapi, uvicorn | 12 REST routers, 10 WS channels | is the dashboard | Existing API test suite | Process crash | systemd restart policy | None |
| Dashboard frontend | PASS | `bonbon_operator_api/frontend` | React/TS/Vite | consumes REST/WS above | is the UI | Manual/preview-verified | Blank page on API unreachable | Retry/backoff + "backend unreachable" banner | None |
| 10.1" touchscreen / kiosk mode | PARTIAL | none | Chromium `--kiosk` (not present) | n/a | n/a | none | Browser chrome visible, no touch calibration | Manual restart | Kiosk launch script, autologin, touch calibration |
| System monitoring (CPU/RAM/disk/temp) | PASS | `bonbon_operator_api` aggregator | psutil-fed topics | `/robot/status/performance`, `/ws/pi-efficiency` | Overview + System tabs | Existing | Stale data if source node down | `available:false` reported honestly | None |
| Deployment readiness | PASS | `devops/scripts/boot_topology.py` | pure Python | `/deployment/boot-topology`, `/ws/boot-topology` | Deployment card | 12 tests (`test_boot_topology.py`) | Missing json → `available:false` | Re-run validator | None |
| Logs/alerts | PASS | `ws_router.py`, `audit_logger.py` | n/a | `/ws/live-logs`, `/ws/safety-events`, `/diagnostics/audit` | Diagnostics tab | Existing | WS disconnect | Client auto-reconnect | None |
| Diagnostics (tests/known-issues) | PASS | `project_status_api.py` | reads `devops/test-results/latest.json`, `known_issues.json` | `/diagnostics/test-results`, `/diagnostics/known-issues` | Diagnostics tab | Existing | File missing → honest `available:false` | Re-run test sweep | None |
| Multi-Pi awareness (routing) | MISSING | n/a | ROS_DOMAIN_ID + DDS discovery | none yet | none yet | none | Dashboard silently can't reach Pi-2/3 topics | n/a | Phase 2/7 network config |

## PI-2 — ASR / LLM / Face / Human Interaction (192.168.10.12)

| Component | Status | Package/Node | Driver/Lib | Topics | Dashboard Visibility | Test Coverage | Failure Mode | Recovery | Dev Needed |
|---|---|---|---|---|---|---|---|---|---|
| ReSpeaker XVF3800 (4-mic + DOA) | PASS | `bonbon_hal/microphone_node` | `RespeakerDriver` (sounddevice + USB HID) | `/bonbon/speech/audio`, `/bonbon/speech/mic_node/health` | none yet | HAL driver tests | USB disconnect | Falls back to `UsbMicDriver`/`MockMicDriver` | Phase 8 dashboard wiring |
| OAK-D Lite camera | **FAIL/MISSING** | none | depthai (not integrated) | none | none | none | Falls back to generic USB camera, loses depth+autofocus | Falls back to `UsbCameraDriver` | New `OAKDLiteDriver` in `bonbon_hal` |
| Speaker + PAM8610 amp | PARTIAL | `bonbon_hal/speaker_node` | `AlsaSpeakerDriver` (generic ALSA) | `/bonbon/speech/speaker_node/health` | none yet | HAL driver tests | No amp-specific gain control | Generic ALSA volume works | Optional: PAM8610-specific tuning |
| ASR (STT) | PASS | `bonbon_speech/speech_node` | Whisper/faster-whisper | `/bonbon/speech/speech_commands` | Speech tab | Existing | Low-confidence transcript | Confidence gating already exists | None |
| VAD | PASS | `bonbon_speech/speech_node` | Silero VAD | internal to speech_node | Speech tab | Existing | n/a | 4-state hysteresis handles noise | None |
| Local Ollama LLM gateway | PARTIAL | `bonbon_llm/llm_orchestrator_node` | Ollama (local only, verified no cloud path) | `/bonbon/llm/request`, `/bonbon/llm/response` | Language tab | Existing | Default model `llama3.2:3b` too large for Pi-2 8GB target | Falls back per config | Config override to `qwen2.5:0.5b`; Phase 9 benchmark |
| Local RAG | PASS | `bonbon_data_stores` + `bonbon_llm` | ChromaDB, `all-MiniLM-L6-v2` | internal to LLM orchestrator | none yet | Existing | ChromaDB unavailable | FAISS/NumPy fallback exists | None |
| Face recognition (identity) | PARTIAL | inline in `bonbon_vision/vision_node` | opencv_dnn/insightface/deepface | embedded in `/bonbon/vision/persons` | none yet | Existing vision tests | Standalone `face_node.py` quarantined/orphaned | Recognition still runs via vision_node | Dashboard-queryable identity endpoint (Phase 4/8) |
| Multi-person tracking | PASS | `bonbon_multi_person_tracker` | n/a | `/bonbon/persons/tracks` | none yet (Phase 8 gap) | 53/53 tests | Track ID switch | ID-switch metric exists (prior brief) | Phase 8 dashboard card |
| Object intelligence | PARTIAL→improving | `bonbon_object_intelligence`, `bonbon_vision` | `bonbon_ai_runtime` RuntimeSelector (wired this session) | `/bonbon/objects/status`, `/bonbon/dashboard/object_summary` | none yet | 61/61 + 53/53 tests | Hailo absent on dev machine | Honest CPU/mock fallback | Phase 8 dashboard wiring |
| Gesture intelligence | PARTIAL | `bonbon_gesture` | n/a | `/bonbon/gesture/events`, `/bonbon/gesture/status` | none yet | 94 tests | `go_away`/`pointing_at_object`/`folded_hands` never emitted | 12/16 types work | Perception-brief Phase 5 |
| Affective AI (emotion) | PARTIAL | `bonbon_affective_ai` | n/a | face/text per-person; voice under `"_global"` key (bug) | none yet | Existing | Voice emotion not attributed to speaker | Face/text emotion unaffected | Perception-brief Phase 4 |
| Human state fusion | PASS | `bonbon_human_state_fusion` | n/a | `/bonbon/human/state` (per prior audit naming) | none yet | 73/73 tests | n/a | n/a | Phase 8 dashboard wiring |
| TTS | PASS | `bonbon_tts` | Piper TTS (local) | `/bonbon/behavior/speech_request`, `/bonbon/speech/audio_output` | TTS tab | Existing | Piper unavailable | MockTTS fallback | None |
| Duplicate camera/mic risk | PASS (clean) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | None — verified single device-owner per sensor |

## PI-3 — Navigation / Motion / Safety (192.168.10.13)

| Component | Status | Package/Node | Driver/Lib | Topics | Dashboard Visibility | Test Coverage | Failure Mode | Recovery | Dev Needed |
|---|---|---|---|---|---|---|---|---|---|
| RPLiDAR A2M12 | PASS | `bonbon_hal/lidar_node` | `RplidarDriver` | `/bonbon/lidar/scan` | none yet | HAL tests | Serial disconnect | HAL health topic | Phase 8 dashboard wiring |
| Cytron SmartDrive MDDS30 | **MISSING** | none | none | none | none | none | Base cannot move at all | none | New driver, ground-up |
| Rhino 24V drive motors | **MISSING** | none | none | `/cmd_vel` published by safety_gate but unconsumed | none | none | Base cannot move at all | none | New `bonbon_drive_motors` package + odometry |
| NEMA 17 closed-loop steppers | **MISSING** | none | none | none | none | none | n/a (not yet used by any joint) | none | New driver if steppers are load-bearing for any joint |
| 25kgcm digital servos (head/arm) | PASS (Dynamixel-compatible) | `bonbon_hal/servo_node` | `DynamixelDriver` | `/bonbon/servo/{neck,arm}/{command,state}` | none yet | HAL tests | Servo comms timeout | Reports fault state | Verify exact torque-rating part number match |
| Navigation (Nav2) | PASS | `bonbon_navigation` | Nav2 (real, not stub) | `/navigation/status`, `NavigateToPose` action | Navigation status (partial) | Existing | Planner failure | Nav2 recovery behaviors | None structurally; needs drive motors to actually move |
| Safety Supervisor | PASS (singleton) / PARTIAL (inputs) | `bonbon_safety/safety_supervisor_node` | n/a | subscribes 14 topics incl. lidar/imu/battery/servo/vision/health; does NOT yet subscribe gesture/human-state | Safety tab | Existing | n/a | n/a | Subscribe `/bonbon/gesture/events`, `/bonbon/human/state` (Phase 6/3) |
| E-stop | PASS | `bonbon_hal/estop_node` + `gpio_estop_driver` | GPIO 17/18 | `/bonbon/estop/state` | Safety tab | Existing | GPIO fault | Hardware relay path independent of software | None |
| Degraded motion mode | PARTIAL | `bonbon_perception_efficiency_node` (perception only) | n/a | `/bonbon/perception_efficiency/degraded_mode` | Pi-efficiency card | Existing | No motion-specific degraded mode | Velocity caps exist in safety gate (CAUTION/DOCKING) | Explicit degraded-motion state machine (Phase 3/6) |
| Motion command authority chain | PASS (verified clean) | `bonbon_safety/safety_gate_node` | n/a | sole publisher of `/cmd_vel`, `/bonbon/servo/*/command` | Safety tab | Existing | Safety-state timeout (2.0s) → zero Twist | Watchdog already implemented | Extend across network boundary (Phase 3) |
| Joint/servo status | PASS | `bonbon_hal/servo_node` | Dynamixel telemetry | `/bonbon/servo/{neck,arm}/state` | none yet | Existing | n/a | n/a | Phase 8 dashboard wiring |
| Duplicate safety-supervisor risk | PASS (resolved) | n/a | systemd `Conflicts=` + 2 validators | n/a | Deployment card | 12 tests | n/a | n/a | Extend validators to check across 3 Pis (Phase 8) |

## Cross-cutting (not owned by one Pi)

| Component | Status | Evidence | Dev Needed |
|---|---|---|---|
| ROS_DOMAIN_ID / DDS network discovery | **MISSING** | Zero occurrences repo-wide | Phase 2/7: per-Pi env config + DDS profile |
| Per-Pi launch files | **MISSING** | Only `bringup.launch.py` (monolithic) + per-subsystem (single-Pi modular) exist | Phase 2: `pi1_bringup.launch.py`, `pi2_bringup.launch.py`, `pi3_bringup.launch.py` |
| Per-Pi efficiency profile | **MISSING** | `config/pi_efficiency_profile.yaml` is one unscoped file | Phase 2/7: split by role |
| Inter-Pi heartbeat | **MISSING** | No `/bonbon/pi{1,2,3}/heartbeat` topic exists | Phase 2/7 |
| Dashboard network-reachability of Pi-2/Pi-3 topics | **MISSING** | Hardcoded topic names assume localhost DDS | Phase 2/7 |
