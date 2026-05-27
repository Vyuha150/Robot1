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
