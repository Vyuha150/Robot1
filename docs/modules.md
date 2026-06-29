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

## bonbon_perception and bonbon_vision

Vision and perception packages.

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
