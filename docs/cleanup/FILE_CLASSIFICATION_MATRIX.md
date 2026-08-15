# File Classification Matrix

**Phase 2.** Classifies every top-level directory and every one of the 44 `ros2_ws/src/` packages. Evidence gathered by 5 parallel research passes (top-level dirs; perception/vision cluster; speech/affective/LLM cluster; safety-critical cluster; bringup/dashboard/data cluster), then **cross-checked by hand against files I read directly** — 3 items below were corrected from what the initial research reported, see "Corrections applied" at the bottom. Nothing in this document has been deleted, moved, or edited — classification only.

**Legend:** KEEP_PRODUCTION · KEEP_HARDWARE_GATED · KEEP_TEST · KEEP_DOCS · KEEP_CONFIG · MERGE_DUPLICATE · REFACTOR_NEEDED · REMOVE_DEAD · REMOVE_OBSOLETE · REMOVE_GENERATED_CACHE · QUARANTINE_UNVERIFIED · BLOCKED_NEEDS_HARDWARE_CONFIRMATION

## Top-level directories/files

| Path | Purpose | Used by | Safety relevance | Recommendation | Evidence |
|---|---|---|---|---|---|
| `Bonbon-robot/` | Empty nested git repo, 0 commits | nothing | none | **REMOVE_OBSOLETE** | `git log` inside it: "no commits yet"; only content is `.git/`; no `.gitmodules` in outer repo referencing it |
| `bonbon_behavior_validation/` | Behavior Oracle / safety-assertion scoring framework for simulated scenarios | `bonbon_operator_api/api/validation_api.py`, ~15 files in `tests/production/*` | low (validates offline, not in live control path) | KEEP_TEST | Real imports found, guarded try/except |
| `bonbon_field_learning/` | Pure-Python (no rclpy) field-pilot learning loop, ingests OracleVerdicts from simulation | `validation_api.py`, `tests/production/test_field_pilot_learning_scenarios.py` | none (disconnected from live telemetry) | KEEP_TEST | Confirmed no rclpy import anywhere in package |
| `config/` | Runtime YAML (distributed/, edge_ai/, hardware_telemetry/, models/, runtime/) | Loaded by ROS2 nodes + launch files at runtime | **high** — `pi_navigation_safety.yaml`, `safety_separation.yaml` gate safety behavior | KEEP_CONFIG | Referenced from launch/edge_ai files and Dockerfiles |
| `deploy/` | One-off Pi-2 deployment bundle | `deploy/*.tar.gz` gitignored; 3 tracked files (manifest/exclude/benchmark) referenced only from historical docs | low | **REMOVE_GENERATED_CACHE** (tarball) / consider moving 3 tracked files to `docs/` as historical record (Phase 10 decision) | `.gitignore:40` excludes `deploy/*.tar.gz`; no code/CI reads any of it |
| `deployment/` | Real deployment engineering tree (compose/docker/systemd/security/monitoring/ota) | Root compose files `include:` these; Dockerfiles build the runtime images nav/safety run in | high | KEEP_PRODUCTION | `docker-compose.robot.yml` includes `deployment/compose/docker-compose.robot.yml` |
| `docker-compose.{dev,robot,simulation}.yml` (root) | Thin 2-line `include:` wrappers around `deployment/compose/` files of the same name | Entry point for `docker compose -f docker-compose.robot.yml up` | low (indirection only) | KEEP_PRODUCTION — **not duplicates**, confirmed by direct diff | ~60 bytes each, single `include:` directive |
| `devops/` | Release tooling scripts + tests | `.github/workflows/ci.yml:28` (`mypy devops`), `.github/workflows/release.yml:31,37` (`release_version.py`, `verify_release.py`) | low | KEEP_PRODUCTION | Directly invoked by CI, not orphaned |
| `founder_command_center/` | Separate FastAPI+React CRM/business-ops product (leads, influencers, student clubs) | Nothing — zero references found from `ros2_ws`, `bonbon_field_learning`, `bonbon_behavior_validation`, or `deployment` | none | **QUARANTINE_UNVERIFIED — needs your confirmation, not a unilateral removal** | README explicitly describes a CRM for "J V Kalyan," zero mention of robot/ROS2/hospital anywhere in it |
| `launch/edge_ai/*.launch.py` (4 files) | Top-level 3-Pi edge-AI launch entry points | Invoked by `scripts/edge_ai/start_{ai,nav,ui}_pi.sh`; launches safety_supervisor/safety_gate/motion_approval_gateway/estop on nav Pi | **high** | KEEP_PRODUCTION, safety-critical, elevated review care | `nav_pi_edge.launch.py` header: "this is the ONE Pi where wheel/stepper/servo/battery HAL state" runs |
| `models/` | Piper TTS voice model (61M), LFS-tracked | TTS pipeline | none | KEEP_PRODUCTION | `.gitattributes` `*.onnx filter=lfs`; `git lfs ls-files` confirms |
| `requirements/pi2_requirements.txt` | Pi-2 AI-stack Python dependency manifest | `deployment/docker/Dockerfile.ai:90,94`; `tests/_ai_stack_gates.py` | low | KEEP_PRODUCTION | `COPY`'d + `pip install -r`'d in Dockerfile |
| `samples/` | 2 WAV ASR test fixtures, LFS-tracked | `tests/speech_ai/test_asr_router.py`, `scripts/ai_models/benchmark_all_models.py` | none | KEEP_TEST | Real test consumers found |
| `scripts/` | Deployment/ops/model-download scripts, incl. `edge_ai/start_{ai,nav,ui}_pi.sh` | `start_nav_pi.sh` is the operational entrypoint to the safety-critical launch chain | high (indirect) | KEEP_PRODUCTION | Direct call chain confirmed |

## ros2_ws/src/ packages (44 total)

### Perception/vision cluster

| Package | Purpose | Recommendation | Evidence |
|---|---|---|---|
| `bonbon_perception` | Own YOLO/HOG detector + own face pipeline, full duplicate of `bonbon_vision` | **REMOVE_DEAD** | `launch/perception.launch.py.disabled`, emptied `console_scripts`, **zero** repo-wide `import bonbon_perception` hits |
| `bonbon_vision` | Canonical camera pipeline: YOLO detection, face detect/recognize, simple tracker, privacy anonymization | KEEP_PRODUCTION | Wired `bringup.launch.py:136`, `docker-compose.pi2.yml:97` |
| `bonbon_perception_ai` | Fusion/reasoning layer over `bonbon_vision`'s output — no detector code of its own | KEEP_PRODUCTION | Wired `bringup.launch.py:155`, `docker-compose.robot.yml:56`; grep confirms no YOLO/cv2 code |
| `bonbon_perception_efficiency` | Advisory-only frame-sampling/degraded-mode coordinator, never commands/bypasses safety | KEEP_PRODUCTION | Wired `bringup.launch.py:164-166` |
| `bonbon_object_intelligence` | Object permanence/calibration/OCR layered on `bonbon_vision`'s output — GAP-E10 fix still holding | KEEP_PRODUCTION | Wired `bringup.launch.py:145`, `docker-compose.pi2.yml:130`; no detector code re-appeared |
| `bonbon_gesture` | Gesture recognition, flags safety-relevant gestures | KEEP_PRODUCTION | Wired `bringup.launch.py:150`, `docker-compose.pi2.yml:131`; `logic/safety_classifier.py` feeds safety supervisor |
| `bonbon_multi_person_tracker` | Person identity lifecycle FSM, fills gap none of the other 3 trackers cover — disclaimed overlap in its own README | KEEP_PRODUCTION | Wired `bringup.launch.py:146-148`, `docker-compose.pi2.yml:129` |
| `bonbon_spatial` | Proxemics/zones/collision-prediction, distinct "spatial/robot-frame" tracker | KEEP_PRODUCTION | Wired `bringup.launch.py:144` |

### Speech/affective/LLM cluster

| Package | Purpose | Recommendation | Evidence |
|---|---|---|---|
| `bonbon_speech` | Live VAD→wake-word→Whisper STT node | KEEP_PRODUCTION | Wired `bringup.launch.py:137`, `human_ai_bringup.launch.py:83`, compose pi2/robot |
| `bonbon_speech_ai` | Real, tested ASR/TTS router + language-detector + normalizer library, **not imported by `bonbon_speech`** | **QUARANTINE_UNVERIFIED** (real, orphaned — wire-in vs. remove is a real decision) | `docs/SPEECH_AI_UPGRADE_REPORT.md` already documents this gap; re-verified still accurate, zero external importers |
| `bonbon_tts` | Live TTS node (Piper backend, safety_gate) | KEEP_PRODUCTION | Wired `bringup.launch.py:184`, compose pi2/robot |
| `bonbon_affective_ai` | Face/voice/text emotion fusion | KEEP_PRODUCTION | Wired `bringup.launch.py:149`, `human_ai_bringup.launch.py:112` |
| `bonbon_speaker_intelligence` | Speaker identity/turn-building | KEEP_PRODUCTION | Wired `bringup.launch.py:152` |
| `bonbon_llm` | LLM orchestrator; verified no direct motor/nav path (`command_filter.py:63-82` regex-blocks cmd_vel/nav2/motor) | KEEP_PRODUCTION | Wired `bringup.launch.py:156`, `human_ai_bringup.launch.py:127` |
| `bonbon_sarvam_adapter` | Optional commercial Sarvam ASR/TTS client, fails closed | KEEP_HARDWARE_GATED | Needs real Sarvam credentials; reached only via dormant `bonbon_speech_ai` path |
| `bonbon_ai_model_registry` | Model registry/router/license-guard library | KEEP_PRODUCTION (library); `model_health_monitor_node` entry point unreferenced | Imported directly by `bonbon_operator_api` |
| `bonbon_ai_runtime` | Vision-inference backend selector (CPU/TensorRT/Hailo) | KEEP_HARDWARE_GATED | Imported by `bonbon_vision/detectors/runtime_adapter_detector.py`, the production detector |
| `bonbon_edge_ai_runtime` | Pi-wide task router + safety-separation guard + cache/resource-guard | **KEEP_PRODUCTION — corrected, see below** | `edge_ai_runtime_node` wired into `launch/edge_ai/ai_pi_edge.launch.py:72-75,130` |

### Safety-critical cluster (all KEEP_PRODUCTION — see dedicated safety audit)

| Package | Role in safety chain |
|---|---|
| `bonbon_safety` | THE authoritative Safety Supervisor + Safety Gate; sole publisher of `/cmd_vel`, servo/stepper commands |
| `bonbon_distributed_safety` | Cross-Pi heartbeat/liveness reporting only — non-authoritative, complementary to `bonbon_safety` |
| `bonbon_authority_manager` | Advisory deployment-mode/degraded-mode broadcaster — explicitly excluded from the approval chain |
| `bonbon_motion_approval_gateway` | THE Safety Gateway — sole subscriber of proposal topics, fail-closed if no SafetyState |
| `bonbon_hal` | Hardware Abstraction Layer — motor/servo write only reachable via gated topics, no bypass found |
| `bonbon_actuation` | Publishes only to `*_command_raw`, routed through the safety gate — "safety gate is never bypassed" (own docstring) |
| `bonbon_base_controller` | "Has NO authority of its own... never originates motion" (own docstring); subscribes only `/cmd_vel` |
| `bonbon_navigation` | Enqueues Nav2 goals exclusively from `/bonbon/motion/approved_command`; "NEVER publishes directly to /cmd_vel" |
| `bonbon_navigation_bringup` | Composition-only launch package, correct boot order (safety→HAL→controller→actuation→gateway→navigation) |
| `bonbon_actions` | Interface-only (`ExecuteMotionSequence.action`); no consuming node located — flagged for Phase 5 follow-up, not a bypass |

**Direct-control-path check result: no bypass found anywhere in the repo.** See `DANGEROUS_CODE_AUDIT.md` (Phase 5) for the full writeup — summarized here since the evidence came from this phase's research.

### Bringup/dashboard/data cluster

| Package | Purpose | Recommendation | Evidence |
|---|---|---|---|
| `bonbon_bringup` | Monolithic single-host/CI/Docker composition of the full stack | KEEP_PRODUCTION | Docker entrypoint |
| `bonbon_human_ai_bringup` | Pi-2 bringup, explicitly HAL-scoped to camera/mic/speaker only | KEEP_HARDWARE_GATED | Comment cites a prior "accidentally launch full stack" bug as the reason for the scoping |
| `bonbon_ui_api_bringup` | Pi-1 bringup: operator_api + co-located fault_manager | KEEP_HARDWARE_GATED | Comment: avoids "three redundant instances" of fault_manager |
| `bonbon_patient_kiosk_bringup` | Separate kiosk-host bringup | KEEP_HARDWARE_GATED | README distinguishes from ui_api_bringup's staff dashboard |
| `bonbon_operator_api` | Staff dashboard backend (FastAPI+WS, JWT, command dispatch via `safety/command_validator.py`) | KEEP_PRODUCTION | Deployed via `ui_api_bringup` |
| `bonbon_patient_kiosk` | Patient-facing kiosk backend (intake/queue/map/panic-button) | KEEP_PRODUCTION; **REFACTOR_NEEDED** for its auth layer | Own docstring: "Pattern-copied from bonbon_operator_api.auth.auth_manager" — real code duplication |
| `bonbon_data_stores` | Central SQLite+vector persistence, RAG engine | KEEP_PRODUCTION | Included first in `bringup.launch.py` |
| `bonbon_data_feedback` | Failure-case logging, privacy-safe retention | KEEP_PRODUCTION | Included in `bringup.launch.py` step 6c |
| `bonbon_fault_manager` | Classifies raw HAL faults into a live component registry | KEEP_PRODUCTION | `/bonbon/fault_manager/registry` consumed by `operator_api/status_aggregator.py` |
| `bonbon_hardware_telemetry` | Battery/joint/wheel/Pi-resource metrics | **KEEP_PRODUCTION — corrected, see below** | Wired `launch/edge_ai/{ai,nav,ui}_pi_edge.launch.py` with per-Pi `pi_role` |
| `bonbon_distributed_network_monitor` | Chrony clock-offset/network-health per Pi | **KEEP_PRODUCTION — corrected, see below** | Wired `launch/edge_ai/{ai,nav,ui}_pi_edge.launch.py` |
| `bonbon_human_state_fusion` | Fuses identity/emotion/gesture/speech into one `HumanState`, explicitly non-duplicative of upstream fusion | KEEP_PRODUCTION | Included in `bringup.launch.py` AI group + `human_ai_bringup` |
| `bonbon_behavior_engine` | Central decision engine; LLM output gated through `LLMCommandGate`/`ProposalEvaluator` | KEEP_PRODUCTION | Core of the safety-gated decision chain |
| `bonbon_msgs` | Pure interface package (51 `.msg` files) | KEEP_PRODUCTION | No nodes, depended on by nearly everything |
| `bonbon_srvs` | Pure interface package (16 `.srv` files) | KEEP_PRODUCTION | No nodes |
| `bonbon_simulation` | Pre-hardware validation suite (headless CI + full Gazebo) | KEEP_PRODUCTION | CI/validation tooling, distinct `launch/` set |

## Corrections applied (agent findings overridden after direct verification, then further refined in Phase 8)

Three packages were initially reported by their respective research passes as "not referenced by any bringup `.launch.py`" because those passes searched `ros2_ws/src/*/launch/` and the `*_bringup` packages but missed the top-level `launch/edge_ai/` directory. A first-pass correction (below, preserved for the audit trail) said all three were `KEEP_PRODUCTION` on the basis that `launch/edge_ai/*_pi_edge.launch.py` wires them in. **Phase 8's systemd/docker-compose cross-reference then found this first correction was itself incomplete** — `launch/edge_ai/*_pi_edge.launch.py` is real code, but it is not what actually runs in production. See `DEPLOYMENT_MODE_CONFLICT_REPORT.md` for the full, final finding. Summary:

- **`bonbon_hardware_telemetry`** — real, tested, correctly wired into `launch/edge_ai/*_pi_edge.launch.py`, but that launch file is **not invoked anywhere** in the real `deployment/systemd/pi{1,2,3}/*.service` → `docker-compose.pi{1,2,3}.yml` chain (confirmed: zero references to `hardware_telemetry` in any of the 3 real compose files). **Final status: KEEP_HARDWARE_GATED, not currently running in production** — real code, correct dashboard consumer already built, but the producer node has no deployed launch path today.
- **`bonbon_distributed_network_monitor`** — **genuinely live in production**, confirmed via a *different* path than initially found: all 3 Pis' `distributed-liveness`/`ros2-support` docker-compose services directly `ros2 run bonbon_distributed_network_monitor network_monitor_node --ros-args -p pi_role:=...` (`docker-compose.pi1.yml`, `.pi2.yml`, `.pi3.yml`), not via `launch/edge_ai/`. **Final status: KEEP_PRODUCTION, confirmed running.**
- **`bonbon_edge_ai_runtime`** — same situation as `bonbon_hardware_telemetry`: real, tested, wired into `launch/edge_ai/ai_pi_edge.launch.py`, but that file is never invoked by the real `docker-compose.pi2.yml` (confirmed: its 10 real services are `hal, asr, vision, perception-fusion, llm, behavior-engine, tts, distributed-liveness, dashboard-api, dashboard-web` — no edge-ai/task-router service exists). **Final status: KEEP_HARDWARE_GATED, not currently running in production.**

This is the accurate, final picture — see `DEPLOYMENT_MODE_CONFLICT_REPORT.md` (Phase 8) for the complete three-generation launch-mechanism analysis and its implications.
