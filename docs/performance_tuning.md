# Performance Tuning

## ROS2

- Keep high-rate sensor topics on appropriate QoS profiles.
- Use reliable/transient-local QoS for safety state and e-stop state.
- Avoid blocking callbacks in lifecycle nodes.
- Monitor topic freshness, not only process liveness.
- Keep CPU-heavy AI inference isolated from safety and navigation processes.

## Navigation

- Tune Nav2 costmap inflation radius for the robot footprint.
- Keep safety margins conservative in hospitals/crowds.
- Tune recovery behavior timeouts in simulation before hardware rollout.
- Monitor replanning latency and recovery success rate.
- Use RTAB-Map database paths on persistent storage.

## Perception and AI

- Track perception latency, detection confidence, and stale frames.
- Use mock models for CI and real models for lab/staging.
- Keep model volumes read-only in production.
- Watch memory growth during long-duration runs.

## Speech and TTS

- Monitor STT latency and confidence.
- Use noise profiles in simulation before noisy deployments.
- Track TTS queue length and emergency announcement latency.

## Data Stores

- Keep SQLite databases on reliable storage.
- Run periodic backups.
- Track vector/RAG index size and query latency.
- Apply privacy retention policies consistently.

## Deployment

- Use Docker layer caching in CI.
- Split CI into package matrices as the repo grows.
- Keep rollback artifacts on robot-local storage.
- Use Prometheus alerts for CPU, memory, disk, battery, stale topics, and safety events.
