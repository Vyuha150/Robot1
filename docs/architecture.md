# Architecture

BonBon uses a layered ROS2 architecture.

## Runtime Layers

1. Hardware abstraction layer
   Drivers publish normalized sensor/actuator state and health topics. Hardware failures become `HalFault` and health events.

2. Safety layer
   `bonbon_safety` evaluates e-stop, lidar, IMU, bumper, thermal, battery, person proximity, servo state, watchdog health, and fault events. It publishes safety state and enforces reset requirements.

3. Navigation layer
   `bonbon_navigation` integrates Nav2, RTAB-Map, localization monitoring, goal management, recovery, human-aware costmaps, battery routing, and docking. Motion commands go through safety-gated velocity.

4. Perception and speech layer
   Vision/perception packages produce object/person state and scene understanding. Speech packages produce transcriptions and command messages. TTS publishes spoken responses and emergency announcements.

5. AI and memory layer
   `bonbon_llm` interprets user intent, applies command filtering and authorization, retrieves context from RAG/data stores, and emits behavior recommendations.

6. Operator and API layer
   `bonbon_operator_api` exposes authenticated HTTP/WebSocket endpoints for dashboard status, commands, diagnostics, config, memory, and RAG.

7. Simulation and deployment layer
   `bonbon_simulation` validates scenarios. `deployment/` and `devops/` package, test, monitor, release, deploy, and roll back the robot software.

## Safety-Critical Flow

```text
Dashboard/API or LLM
  -> command validation
  -> SafetyCommandGate
  -> ROS2 bridge/service call
  -> navigation/speech/TTS/safety package
  -> SafetyStopBridge for motion
  -> /bonbon/safety_gate/cmd_vel
  -> SafetyGateNode
  -> /cmd_vel or stop
```

## Deployment Flow

```text
CI validation
  -> signed/checksummed release
  -> config validation
  -> pre-deployment safety checks
  -> remote release directory
  -> docker compose/systemd activation
  -> health checks
  -> post-deployment ROS2/interface checks
  -> audit log
```

## Directory Layout

```text
ros2_ws/src/                 ROS2 packages
deployment/docker/           Runtime Dockerfiles
deployment/compose/          Compose stacks
deployment/systemd/          Robot host service units
deployment/monitoring/       Prometheus/Grafana config
deployment/docs/             DevOps/deployment docs
devops/scripts/              Build/test/deploy/release scripts
devops/config/               Environment-specific config templates
devops/tests/                DevOps validation tests
.github/workflows/           CI and release workflows
docs/                        Platform-level documentation
```
