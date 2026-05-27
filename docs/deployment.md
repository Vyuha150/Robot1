# Deployment Notes

Production deployment is managed by `deployment/`, `devops/`, Docker Compose, systemd, and GitHub Actions.

## Environments

- `local_dev`: local development
- `simulation`: headless simulation and monitoring
- `lab_robot`: hardware lab robot
- `staging_robot`: staging robot
- `production_robot`: real-world production robot

## Docker Images

- `deployment/docker/Dockerfile.ros2`
- `deployment/docker/Dockerfile.ai`
- `deployment/docker/Dockerfile.navigation`
- `deployment/docker/Dockerfile.dashboard`

## Compose Stacks

- `docker-compose.dev.yml`
- `docker-compose.simulation.yml`
- `docker-compose.robot.yml`

## systemd Services

- `bonbon-core.service`
- `bonbon-navigation.service`
- `bonbon-perception.service`
- `bonbon-speech.service`
- `bonbon-tts.service`
- `bonbon-safety.service`
- `bonbon-dashboard.service`
- `bonbon-monitoring.service`

## Pre-Deployment Checks

`pre_deploy_check.py` verifies:

- battery above threshold
- e-stop available
- safety supervisor running
- current robot task paused
- no active navigation
- disk space sufficient
- rollback version available
- config validation state
- service health state
- operator authorization

## Post-Deployment Checks

`post_deploy_check.py` verifies:

- services started
- ROS2 graph healthy
- Safety Supervisor healthy
- sensor topics publishing
- dashboard reachable
- logs active
- metrics active
- no critical errors
- rollback not required

## Release Integrity

Release workflow generates:

- release archive
- SHA256 checksum
- cosign signature
- release metadata

Verify locally:

```bash
python devops/scripts/verify_release.py \
  --artifact bonbon-release.tar.gz \
  --sha256 bonbon-release.tar.gz.sha256
```

## Rollback

Rollback uses:

- `/opt/bonbon/releases/<version>`
- `/opt/bonbon/current`
- `/etc/bonbon/bonbon.env`

Run:

```bash
BONBON_ROBOT_HOST=robot.local devops/scripts/rollback_robot.sh previous-version
```

## Deployment Documentation

Detailed operational docs live under `deployment/docs/`.
