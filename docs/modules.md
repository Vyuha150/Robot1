# Module Guide

This guide summarizes the major BonBon modules and their ownership boundaries.

## bonbon_msgs

Custom message package.

Messages include:

- `AudioChunk`
- `BehaviorRecommendation`
- `BumperState`
- `ContextEvent`
- `DetectedObject`
- `DetectedObjectArray`
- `DockingStatus`
- `HalFault`
- `LLMLog`
- `LLMResponse`
- `MemoryEntry`
- `ModuleHealth`
- `NavigationGoal`
- `NavigationStatus`
- `PersonState`
- `PersonStateArray`
- `RecoveryStatus`
- `RiskEvent`
- `SafetyEvent`
- `SafetyState`
- `SemanticScene`
- `ServoState`
- `ServoStateArray`
- `SpeechCommand`
- `SpeechTranscription`
- `ThermalReadings`
- `TTSRequest`
- `UserIntent`

## bonbon_srvs

Custom service package.

Services include:

- `CancelNavigation`
- `GetNearestCharger`
- `LLMQuery`
- `NavigateTo`
- `SafetyReset`

## bonbon_hal

Hardware abstraction layer for sensors and actuators.

Responsibilities:

- Camera, lidar, IMU, battery, e-stop, microphone, speaker, and servo drivers.
- Hardware health reporting.
- HAL fault publication.
- Mock drivers for tests and simulation.

Important topics:

- `/bonbon/lidar/scan`
- `/bonbon/imu/data_raw`
- `/bonbon/temperature/readings`
- `/bonbon/battery/state`
- `/bonbon/estop/state`
- `/bonbon/vision/camera/color/image_raw`
- `/bonbon/vision/camera/depth/image_raw`
- `/bonbon/hal/fault`
- `/bonbon/<subsystem>/<node>/health`

## bonbon_safety

Safety supervisor and e-stop package.

Responsibilities:

- Safety state machine.
- Threat assessment.
- E-stop integration.
- Watchdog monitoring.
- Incident logging.
- Safety reset service.

Deployment rule:

- Any changes to safety code require safety test suites to pass before merge.

## bonbon_navigation

Navigation package.

Responsibilities:

- Nav2 integration.
- RTAB-Map/AMCL localization.
- Goal management.
- Human-aware costmaps.
- Stuck detection and recovery.
- Docking.
- Low-battery routing.
- Safety-gated velocity.

Important command path:

```text
NavigationNode -> SafetyStopBridge -> /bonbon/safety_gate/cmd_vel -> SafetyGateNode -> /cmd_vel
```

## bonbon_vision

`bonbon_perception` (an earlier, fully duplicate camera/detection/face
pipeline reprocessing the same raw camera feed) was quarantined during the
2026-08-14 cleanup audit — see `docs/cleanup/QUARANTINE_REPORT.md` — and
moved to `_archive/quarantine_cleanup_20260814/bonbon_perception/`. It was
already disabled (launch file `.disabled`, empty `console_scripts`) with
zero repo-wide imports before the move. `bonbon_vision` below is, and has
been, the sole live camera/vision pipeline.

Responsibilities:

- Camera frame handling.
- Object detection.
- Person detection/tracking.
- Face pipeline.
- Privacy guard.
- Vision health reporting.

Important topics:

- `/bonbon/vision/objects`
- `/bonbon/vision/persons`
- `/bonbon/vision/persons_identified`
- `/bonbon/vision/detection_node/health`
- `/bonbon/vision/face_node/health`

## bonbon_perception_ai

Multimodal scene understanding package.

Responsibilities:

- Fuse vision, speech, navigation status, and pose.
- Scene analysis.
- Risk assessment.
- Intent engine.
- Behavior recommendation.
- Memory context handling.

Inputs:

- `/bonbon/vision/objects`
- `/bonbon/vision/persons`
- `/speech/command`
- `/bonbon/nav/status`
- `/bonbon/spatial/pose`

## bonbon_speech

Speech input package.

Responsibilities:

- Wake word detection.
- VAD.
- STT.
- Diarization.
- Audio buffering/preprocessing.
- Speech command publication.

Outputs:

- `/speech/command`
- `/speech/transcription`
- `/health/speech`

## bonbon_tts

Text-to-speech output package.

Responsibilities:

- TTS queueing.
- Backend selection.
- Voice profiles.
- Filler audio.
- Speaker bridge.
- TTS health and metrics.

Typical input:

- `/bonbon/tts/request`

## bonbon_llm

LLM orchestration package.

Responsibilities:

- LLM client and orchestration.
- RAG retrieval.
- Tool registry.
- Command filtering.
- Authorization.
- Personality layer.
- Response logging.

Safety rule:

- LLM tools should emit behavior recommendations or validated commands, not raw actuator control.

## bonbon_data_stores

Data persistence package.

Responsibilities:

- SQLite repositories.
- FAISS vector store.
- Chroma RAG store.
- Privacy and retention management.
- Backup and restore.
- Data store health.

Important services/topics:

- `/bonbon/data_store/health`
- `/bonbon/data_store/health_check`
- `/bonbon/data_store/create_backup`

Coupling warning:

- `bonbon_operator_api` memory/RAG endpoints depend on `bonbon_data_stores` through the ROS2 bridge. Store interface changes can ripple into dashboard/API behavior.

## bonbon_operator_api

FastAPI operator dashboard backend.

Responsibilities:

- JWT auth.
- RBAC.
- Robot status API.
- Command API.
- Diagnostics API.
- Config API.
- Memory/RAG API.
- WebSocket channels.
- Metrics and audit logging.
- ROS2 bridge.

Safety rule:

- Dashboard commands must pass `CommandValidator` and `SafetyCommandGate`.

## bonbon_patient_kiosk

Patient/customer-facing kiosk API for a hospital reception deployment.
Separate from `bonbon_operator_api` (staff-only) — see its own README.

Responsibilities:

- Anonymous, session-scoped patient interaction (no accounts).
- Patient history intake with in-memory-only drafts + encrypted-at-rest submit.
- Appointment booking and walk-in queue/token issuance.
- RAG-grounded chat (proxies `bonbon_llm`'s `/llm/query`) and wayfinding/escort.
- Staff-only, export-only Facility Map Editor (room/doctor labeling → `named_locations` YAML).
- PHI-access audit logging; JWT auth for the staff/admin slice only.

Safety rule:

- Navigation/panic requests pass through its own `KioskSafetyGate` before
  reaching `/navigation/navigate_to` — the same safety-gated service
  `bonbon_operator_api` calls. Never bypasses `bonbon_safety` or
  `bonbon_navigation`'s own pipeline, never live-writes bonbon_navigation's
  named-location registry.

## bonbon_simulation

Simulation validation package.

Responsibilities:

- Scenario configs.
- Headless deterministic scenario runner.
- Gazebo/Ignition-compatible world files.
- Robot URDF/Xacro.
- Sensor/fault/dynamic obstacle simulation.
- Metrics and reports.
- CI-compatible smoke tests.

## Multi-Person Perception Packages

Added/extended in the multi-person perception upgrade. Each consumes
existing pipelines rather than duplicating them — see the dedicated doc per
package for architecture, topics, configs, and troubleshooting.

| Package | Responsibility | Doc |
|---|---|---|
| `bonbon_object_intelligence` | Object permanence, confidence calibration, OCR hook, depth association — over `bonbon_vision`'s existing detections | [OBJECT_INTELLIGENCE.md](OBJECT_INTELLIGENCE.md) |
| `bonbon_multi_person_tracker` | Person identity lifecycle (the one genuinely new tracking capability) | [MULTI_PERSON_TRACKING.md](MULTI_PERSON_TRACKING.md) |
| `bonbon_gesture` (extended) | + multi-person gesture-to-identity assignment | [GESTURE_INTELLIGENCE.md](GESTURE_INTELLIGENCE.md) |
| `bonbon_speaker_intelligence` | Persistent speaker identity, transcript-to-speaker mapping, audio-visual association | [SPEAKER_INTELLIGENCE.md](SPEAKER_INTELLIGENCE.md) |
| `bonbon_human_state_fusion` | Per-person fusion of identity + emotion + gesture + speech into `HumanState` | [HUMAN_STATE_FUSION.md](HUMAN_STATE_FUSION.md) |
| `bonbon_behavior_engine` (extended) | + the 10 multi-person behavior rules, dispatched through the existing safety gate | [REAL_WORLD_INTERACTION_SCENARIOS.md](REAL_WORLD_INTERACTION_SCENARIOS.md) |

See also [AUDIO_VISUAL_PERSON_ASSOCIATION.md](AUDIO_VISUAL_PERSON_ASSOCIATION.md),
[TESTING_PERCEPTION_INTELLIGENCE.md](TESTING_PERCEPTION_INTELLIGENCE.md), and
the Multi-Person Perception section of [performance_tuning.md](performance_tuning.md).

## Efficiency and Data Feedback Packages

Added in the efficiency/optimization upgrade. Neither detects anything
itself — both coordinate/observe existing pipelines. See
[EFFICIENCY_ARCHITECTURE.md](EFFICIENCY_ARCHITECTURE.md) for the full audit
findings and design rationale.

| Package | Responsibility | Doc |
|---|---|---|
| `bonbon_perception_efficiency` | Confidence policy, frame sampling, stale-frame drop, bounded queues, active-person focus, load shedding, degraded mode, metrics — all advisory | [EFFICIENCY_ARCHITECTURE.md](EFFICIENCY_ARCHITECTURE.md), [PERCEPTION_BUDGET_MANAGER.md](PERCEPTION_BUDGET_MANAGER.md) |
| `bonbon_data_feedback` | Failure-case logging, hard negatives, dataset export/versioning, model evaluation tracking, privacy-safe retention | [DATA_STRATEGY.md](DATA_STRATEGY.md), [FAILURE_CASE_LEARNING.md](FAILURE_CASE_LEARNING.md), [PRIVACY_SAFE_DATA_COLLECTION.md](PRIVACY_SAFE_DATA_COLLECTION.md) |

See also [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md) and
[OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md).

## deployment and devops

Operational deployment system.

Responsibilities:

- Docker images.
- Compose stacks.
- systemd units.
- CI/release workflows.
- Config validation.
- Pre/post deployment checks.
- Release versioning.
- Checksum verification.
- Rollback.
- Monitoring.
- Documentation and tests.
