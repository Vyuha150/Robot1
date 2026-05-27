# Deployment Architecture

The deployment module is split into four layers.

1. Build and validation layer: `.github/workflows/ci.yml`, `pyproject.toml`, `devops/scripts/build_ros2.sh`, `devops/scripts/run_tests.sh`, and `devops/scripts/run_simulation_smoke.sh`.
2. Runtime packaging layer: Dockerfiles in `deployment/docker/` and Compose stacks in `deployment/compose/`.
3. Robot operations layer: `deploy_to_robot.sh`, `rollback_robot.sh`, `pre_deploy_check.py`, `post_deploy_check.py`, `health_check.sh`, `collect_logs.sh`, and systemd units.
4. Observability layer: Prometheus scrape config, Grafana dashboards, service health checks, logs, and release metadata.

The deployment path is intentionally gated. A robot should only consume a version that passed CI, produced signed/checksummed artifacts, passed config validation, passed pre-deployment safety checks, and passed post-deployment health checks.

## Runtime Topology

Robot runtime containers:

- `core`: base ROS2 bringup
- `navigation`: Nav2 and RTAB-Map
- `ai`: LLM orchestration and AI services
- `perception`: perception AI launch
- `speech`: microphone, VAD, STT, wake word
- `tts`: speech synthesis
- `safety`: safety supervisor stack
- `dashboard-api`: operator API
- `monitoring`: Prometheus

Persistent mounts:

- `/etc/bonbon`: config, read-only inside containers
- `/var/lib/bonbon`: data stores and Prometheus state
- `/opt/bonbon/models`: model files, read-only
- `/opt/bonbon/maps`: maps, read-only
- `/var/log/bonbon`: runtime logs

## Safety Deployment Flow

1. Validate config for the target environment.
2. Verify release checksum when an artifact is supplied.
3. Run pre-deployment safety checks.
4. Copy Compose file, health scripts, and environment config.
5. Materialize `/etc/bonbon/bonbon.env` from the selected environment runtime config.
6. Update `/opt/bonbon/current` symlink.
7. Start containers.
8. Run health and post-deployment checks.
9. Write audit entries for deploy or rollback actions.
