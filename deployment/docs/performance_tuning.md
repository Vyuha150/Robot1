# Performance Tuning

## Docker

- Use BuildKit cache for ROS dependency layers.
- Keep model files outside runtime images and mount them read-only.
- Split AI, navigation, dashboard, and core images so unrelated changes do not rebuild everything.
- Pin base image versions before production release hardening.

## CI

- Split package tests into a matrix once runtime grows.
- Cache Python wheels and ROS dependency metadata.
- Keep deterministic simulation smoke tests fast and reserve full Gazebo runs for scheduled or gated jobs.
- Upload logs and simulation reports only on failure or release branches if artifact storage becomes expensive.

## ROS2

- Keep `ROS_DOMAIN_ID` environment-specific.
- Use topic freshness metrics for sensor health rather than only process health.
- Tune Nav2 and RTAB-Map in simulation before hardware deployment.
- Avoid launching dashboard and AI workloads on the same constrained CPU core set on robot hardware.

## Monitoring

- Keep Prometheus scrape intervals at 15 seconds for normal operation.
- Lower scrape intervals only during lab diagnosis.
- Use histogram buckets for TTS, STT, perception, LLM, and replanning latency.
- Add alert rules for estop events, safety supervisor loss, disk pressure, battery pressure, and stale sensor topics.

## Deployment

- Prefer staging deployments before production.
- Use checksum verification for every production artifact.
- Keep rollback releases on local robot storage to avoid network dependency during rollback.
