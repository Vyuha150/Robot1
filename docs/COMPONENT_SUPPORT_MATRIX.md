# Component Support Matrix (Three-Pi Split)

**Date:** 2026-07-01 (BOM-accuracy corrections added 2026-07-06 — see rows
marked "(2026-07-06)"; the real BOM is `Humanoid_Robot_Components_
Dimensions.xls`, which confirmed the 3-Pi split and surfaced several rows
below that had gone stale relative to their own linked gap-report entries.)
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
| System monitoring (CPU/RAM/disk/temp) | PASS | `bonbon_operator_api` aggregator | psutil-fed topics | `/robot/status/performance`, `/ws/pi-efficiency` | Overview + System tabs | Existing | Stale data if source node down | `available:false` reported honestly | None |
| Deployment readiness | PASS | `devops/scripts/boot_topology.py` | pure Python | `/deployment/boot-topology`, `/ws/boot-topology` | Deployment card | 12 tests (`test_boot_topology.py`) | Missing json → `available:false` | Re-run validator | None |
| Logs/alerts | PASS | `ws_router.py`, `audit_logger.py` | n/a | `/ws/live-logs`, `/ws/safety-events`, `/diagnostics/audit` | Diagnostics tab | Existing | WS disconnect | Client auto-reconnect | None |
| Diagnostics (tests/known-issues) | PASS | `project_status_api.py` | reads `devops/test-results/latest.json`, `known_issues.json` | `/diagnostics/test-results`, `/diagnostics/known-issues` | Diagnostics tab | Existing | File missing → honest `available:false` | Re-run test sweep | None |
| Multi-Pi awareness (routing) | PASS (2026-07-06) | `bonbon_ui_api_bringup`, `scripts/bootstrap_pi_network.py` | ROS_DOMAIN_ID=42 + CycloneDDS unicast profile (`config/distributed/cyclonedds_ethernet_profile.xml`, previously referenced but did not exist) | shares DDS domain with Pi-2/Pi-3 | Multi-Pi awareness | `check_inter_pi_communication.py` (not a unit test — a live-network check) | Network/discovery misconfig | `scripts/check_inter_pi_communication.py --role pi1` gives a positive confirmation, distinct from the duplicate-node check | None |
| Component fault registry | PASS (2026-07-06) | `bonbon_fault_manager` | pure-Python classifier (48 tests) + LifecycleNode | `/bonbon/fault_manager/registry` | `component-health` WS channel (extended) | 48/48 tests | Unclassified device/error_code falls back to a conservative, honestly-labeled default | Add a rule to `core/component_rules.py` | None |
| 10.1" touchscreen / kiosk mode | PASS (2026-07-06) | `devops/scripts/launch_kiosk.sh` | Chromium `--kiosk`, waits for dashboard health before opening | n/a | is the touchscreen surface | manual smoke-test only (no hardware in this environment) | Dashboard unhealthy at boot | Script refuses to open kiosk against a dead backend rather than showing a blank/unrecoverable screen | Touch calibration (still open) |

## PI-2 — ASR / LLM / Face / Human Interaction (192.168.10.12)

| Component | Status | Package/Node | Driver/Lib | Topics | Dashboard Visibility | Test Coverage | Failure Mode | Recovery | Dev Needed |
|---|---|---|---|---|---|---|---|---|---|
| ReSpeaker XVF3800 (4-mic + DOA) | PASS | `bonbon_hal/microphone_node` | `RespeakerDriver` (sounddevice + USB HID) | `/bonbon/speech/audio`, `/bonbon/speech/mic_node/health` | `component-health` (2026-07-06, via `bonbon_fault_manager`) | HAL driver tests | USB disconnect | Falls back to `UsbMicDriver`/`MockMicDriver`; classified CRITICAL with concrete recovery guidance by `bonbon_fault_manager` | None |
| OAK-D Lite camera | PASS (corrected 2026-07-06 — this row was stale; resolved earlier as `HARDWARE_SOFTWARE_GAP_REPORT.md` item 3 already documented) | `bonbon_hal/camera_node` | `OAKDLiteDriver` (depthai SDK) | `/bonbon/vision/frames`, `/bonbon/hal/camera_node/health` | `component-health` (2026-07-06) | `test_oakd_lite_driver.py` (7 tests) | SDK missing / read error | Honest `DriverFault("SDK_MISSING")`; falls back to `UsbCameraDriver` backend if reconfigured | None |
| Speaker + PAM8610 amp | PASS (2026-07-06 — mute-pin GPIO control implemented) | `bonbon_hal/speaker_node` | `AlsaSpeakerDriver` + optional PAM8610 mute-pin GPIO (`has_pam8610` param, defaults **off** pending real-hardware verification of whether the mute pin is actually wired) | `/bonbon/speech/speaker_node/health` | `component-health` (2026-07-06) | HAL driver tests (GPIO path not directly unit-tested, matches repo convention of testing Mock drivers, not real GPIO drivers) | GPIO claim failure | Degrades to plain ALSA only (WARNING-level, not FAULT) — amp control was never load-bearing for basic audio | Verify `has_pam8610`/pin wiring on real Pi-2 hardware |
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
| RPLiDAR A2M12 | PASS | `bonbon_hal/lidar_node` | `RplidarDriver` | `/bonbon/lidar/scan` | `component-health` (2026-07-06) | HAL tests | Serial disconnect | HAL health topic; classified FAULT/CRITICAL by `bonbon_fault_manager` with concrete recovery guidance | None |
| Cytron SmartDrive MDDS30 | PASS (corrected 2026-07-06 — this row was stale; resolved earlier, see gap report item 1) | `bonbon_hal/motor_node` + `bonbon_base_controller` | `CytronMDDS30Driver` | `/cmd_vel` → per-wheel speeds | `component-health` (2026-07-06) | 30 tests (`bonbon_base_controller`) | Serial write failure | `bonbon_fault_manager` classifies as FAULT ("base_controller must treat as navigation-halting") | Real-hardware `wheel_base_m` measurement (placeholder 0.40m) |
| Rhino 24V drive motors | PASS (corrected 2026-07-06 — driven via Cytron MDDS30, see row above) | `bonbon_base_controller` | `DiffDriveKinematics`, `OdometryIntegrator` | `nav_msgs/Odometry` | Navigation status | 30 tests | `has_encoders=False` (honest — encoders unconfirmed) | Odometry is explicit open-loop dead-reckoning, never fabricated closed-loop | Confirm encoders fitted on real hardware |
| NEMA 17 closed-loop steppers (HEAD pan, RIGHT ARM shoulder) | PASS (2026-07-06 — real BOM confirms 2x steppers, not a speculative joint) | `bonbon_hal/stepper_node` | `NEMA17ClosedLoopDriver` (STEP/DIR/ENABLE + ALM alarm pin — the one genuinely closed-loop fault signal in this BOM) | `/bonbon/stepper/{command,command_raw}` | `component-health` (2026-07-06) | 23 (`stepper_kinematics`) + 15 (`stepper_driver`) + 4 stall-visibility regression tests | Stall/lost-sync (`StallFaultTracker`, debounced 3-poll confirm/clear) | `bonbon_fault_manager` classifies FAULT with `clear_stall()` guidance; gated through `bonbon_safety/safety_gate_node`'s new stepper path | None |
| 25kgcm digital servos (HEAD tilt, RIGHT ARM elbow/wrist) | PASS (corrected 2026-07-06 — primary hardware is PCA9685, not Dynamixel; this row previously assumed the wrong actuator entirely) | `bonbon_hal/servo_node` | `PCA9685ServoDriver` (16-channel I2C PWM; `DynamixelDriver` kept as a selectable, non-primary backend) | `/bonbon/servo/{neck,arm}/{command,state}` | `component-health` (2026-07-06) | 11 tests (`test_pca9685_servo_driver.py`) | I2C bus error; no load-feedback sensor exists on RC servos (honestly documented, never fabricated) | Reports fault via `_record_fault`; `bonbon_fault_manager` notes no-overload-detection explicitly | None |
| Navigation (Nav2) | PASS | `bonbon_navigation` | Nav2 (real, not stub) | `/navigation/status`, `NavigateToPose` action | Navigation status (partial) | Existing | Planner failure | Nav2 recovery behaviors | None structurally; needs drive motors to actually move |
| Safety Supervisor | PASS (singleton) / PARTIAL (inputs) | `bonbon_safety/safety_supervisor_node` | n/a | subscribes 14 topics incl. lidar/imu/battery/servo/vision/health; does NOT yet subscribe gesture/human-state | Safety tab | Existing | n/a | n/a | Subscribe `/bonbon/gesture/events`, `/bonbon/human/state` (Phase 6/3) |
| E-stop | PASS | `bonbon_hal/estop_node` + `gpio_estop_driver` | GPIO 17/18 | `/bonbon/estop/state` | Safety tab | Existing | GPIO fault | Hardware relay path independent of software | None |
| Degraded motion mode | PARTIAL | `bonbon_perception_efficiency_node` (perception only) | n/a | `/bonbon/perception_efficiency/degraded_mode` | Pi-efficiency card | Existing | No motion-specific degraded mode | Velocity caps exist in safety gate (CAUTION/DOCKING) | Explicit degraded-motion state machine (Phase 3/6) |
| Motion command authority chain | PASS (verified clean) | `bonbon_safety/safety_gate_node` | n/a | sole publisher of `/cmd_vel`, `/bonbon/servo/*/command` | Safety tab | Existing | Safety-state timeout (2.0s) → zero Twist | Watchdog already implemented | Extend across network boundary (Phase 3) |
| Joint/servo status | PASS (corrected 2026-07-06 — telemetry is now PCA9685/NEMA17, see rows above) | `bonbon_hal/servo_node`, `bonbon_hal/stepper_node` | PCA9685/NEMA17 telemetry | `/bonbon/servo/{neck,arm}/state`, `/bonbon/stepper/command` | `component-health` (2026-07-06) | Existing + Workstream 1 tests | n/a | n/a | None |
| Joint topology (real BOM) | PASS (2026-07-06) | `bonbon_actuation/core/gesture_library.py` | `JOINT_ACTUATOR_TYPE`/`JOINT_LOCAL_ID` global joint-ID map | n/a | n/a | 92/92 `bonbon_actuation` tests | n/a | n/a | None — single right arm (shoulder/elbow/wrist) + 2-DOF head (pan/tilt); no left arm, no gripper. Previously assumed a symmetric 7-servo two-arm robot; corrected. |
| Duplicate safety-supervisor risk | PASS (resolved) | n/a | systemd `Conflicts=` + 2 validators | n/a | Deployment card | 12 tests | n/a | n/a | Extend validators to check across 3 Pis (Phase 8) |

## Cross-cutting (not owned by one Pi)

| Component | Status | Evidence | Dev Needed |
|---|---|---|---|
| ROS_DOMAIN_ID / DDS network discovery | PASS (2026-07-06) | `config/distributed/robot_network.yaml` (`ros_domain_id: 42`) + `config/distributed/cyclonedds_ethernet_profile.xml` (previously referenced but did not exist) + `scripts/bootstrap_pi_network.py` applies both to real hardware | None |
| Per-Pi launch files | PASS (2026-07-06) | `bonbon_human_ai_bringup` (Pi-2, existing), `bonbon_ui_api_bringup` (Pi-1, new), `bonbon_navigation_bringup` (Pi-3, new) | None |
| Per-Pi efficiency profile | PARTIAL | `config/distributed/pi_*.yaml`'s `relevant_efficiency_modules` scope `config/pi_efficiency_profile.yaml` by role, but the underlying file is still one unscoped file | Split by role if per-Pi divergence is ever needed |
| Inter-Pi heartbeat | PASS | `bonbon_distributed_safety` publishes `/bonbon/pi{1,2,3}/heartbeat`; `scripts/check_inter_pi_communication.py` (2026-07-06) gives a positive, live confirmation distinct from the duplicate-node check | None |
| Dashboard network-reachability of Pi-2/Pi-3 topics | PARTIAL | `ros2_bridge.py` subscribes cross-Pi topics correctly, but the split-container Docker deployment's lightweight `dashboard-api` container has no `rclpy` (see `docker-compose.pi1.yml` module comment, 2026-07-06) — the bare-metal/systemd single-process path (`bonbon_ui_api_bringup`) does not have this gap | Decide: give the dashboard image a ROS2 base, or build a network-facing bridge process |
