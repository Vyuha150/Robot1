# Configuration Reference

Environment config lives under `devops/config/<environment>/`.

Supported environments:

- `local_dev`
- `simulation`
- `lab_robot`
- `staging_robot`
- `production_robot`

Each environment contains:

- `runtime.env`: environment variables copied to `/etc/bonbon/bonbon.env` on robot hosts
- `services.yaml`: required service and safety policy metadata
- `models.manifest`: robot environments only; relative paths to required model artifacts

## Required Runtime Variables

Common:

- `BONBON_ENV`
- `BONBON_RELEASE_CHANNEL`
- `BONBON_IMAGE_TAG`
- `BONBON_CONFIG_DIR`
- `BONBON_DATA_DIR`
- `BONBON_LOG_DIR`
- `BONBON_MODEL_DIR`
- `BONBON_MAP_DIR`

Robot deployments:

- `BONBON_ROBOT_HOST`
- `BONBON_ROBOT_USER`
- `BONBON_ROBOT_SSH_PORT`
- `BONBON_MIN_BATTERY_PCT`

Runtime secrets:

- `BONBON_JWT_SECRET`
- `BONBON_ADMIN_PASSWORD`

Runtime secrets must be injected on the host or through a secret manager. They must not be committed.

## Validation

Validate local config:

```bash
python3 devops/scripts/validate_config.py --env local_dev
```

Validate production config with runtime secrets:

```bash
python3 devops/scripts/validate_config.py --env production_robot --require-runtime-secrets
```
