# Deployment Notes

## Environment Materialization

Robot Compose uses `/etc/bonbon/bonbon.env`. During deployment, the selected environment's `runtime.env` is copied to the robot and materialized as `bonbon.env`.

Existing runtime secrets are preserved when `bonbon.env` already exists:

- `BONBON_JWT_SECRET`
- `BONBON_ADMIN_PASSWORD`

This prevents a routine deployment from erasing dashboard credentials already provisioned on the robot.

## Release Integrity

`deploy_to_robot.sh` supports optional checksum validation:

```bash
devops/scripts/deploy_to_robot.sh \
  --env production_robot \
  --version production-20260527 \
  --artifact bonbon-release.tar.gz \
  --sha256 bonbon-release.tar.gz.sha256
```

Production deployments should always provide `--artifact` and `--sha256`, and should use artifacts from the signed release workflow.

## Audit Trail

Deployment and rollback actions append to `deployment/logs/deployment_audit.log` by default, or to `BONBON_AUDIT_LOG` when set.

Audit entries include UTC timestamp, local user, action, environment, version, and dry-run state.

## Rollback Layout

Robot hosts use:

- `/opt/bonbon/releases/<version>` for immutable release directories
- `/opt/bonbon/current` as the active symlink
- `/etc/bonbon/bonbon.env` for runtime environment

Rollback changes the symlink and restarts Compose with the rollback version.
