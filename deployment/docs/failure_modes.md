# Failure Modes

This module is designed to fail closed around deployment and release operations.

## Pre-Deployment Failure Modes

- Battery below `BONBON_MIN_BATTERY_PCT`: deployment stops.
- Emergency stop unavailable: deployment stops.
- Safety supervisor not running: deployment stops.
- Robot task not paused: deployment stops.
- Active navigation detected: deployment stops.
- Disk free space below threshold: deployment stops.
- Rollback version unavailable: deployment stops.
- Config validation failure: deployment stops.
- Service health failure: deployment stops.
- Operator authorization missing: deployment stops.

## Release Failure Modes

- Missing artifact: `verify_release.py` fails.
- Missing checksum file: `verify_release.py` fails.
- Checksum mismatch: `verify_release.py` fails.
- Missing signature in production process: production release should not be approved.

## Deployment Failure Modes

- Missing `BONBON_ROBOT_HOST`: deploy script fails before SSH.
- Missing health scripts on target: deploy script now copies them before activation.
- Missing `/etc/bonbon/bonbon.env`: deploy script materializes it from `runtime.env`.
- Missing Docker Compose: service startup fails and post-deploy checks fail.

## Post-Deployment Failure Modes

- systemd service inactive: post-deploy check fails.
- ROS2 graph unhealthy: post-deploy check fails.
- Safety Supervisor unhealthy: post-deploy check fails.
- Sensor topics absent: post-deploy check fails.
- Dashboard unreachable: post-deploy check fails.
- Logs inactive: post-deploy check fails.
- Metrics inactive: post-deploy check fails.
- Critical errors present: post-deploy check fails.
- Rollback required: post-deploy check fails.

## Rollback Failure Modes

- Rollback version missing on robot: rollback fails before symlink switch.
- Services fail after rollback: health and post-deploy checks fail.
- Runtime secrets missing after rollback: dashboard health/auth checks should fail.
