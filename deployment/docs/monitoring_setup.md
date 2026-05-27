# Monitoring Setup

Prometheus config lives at `deployment/monitoring/prometheus/prometheus.yml`.

Grafana dashboards cover:

- robot health
- safety status
- navigation performance
- AI inference performance
- system resources
- module availability
- logs/errors
- deployment version

Required metrics include CPU, memory, disk, ROS2 node health, safety events, navigation failures, TTS/STT/perception/LLM latency, actuation errors, battery state, and emergency stop events.
