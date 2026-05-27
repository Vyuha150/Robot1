# Configuration

Configuration is split across ROS2 package configs, deployment environment configs, runtime secrets, and simulation scenario configs.

## ROS2 Package Configs

Important package config files:

- `ros2_ws/src/bonbon_safety/bonbon_safety/config/safety_params.yaml`
- `ros2_ws/src/bonbon_navigation/config/nav_params.yaml`
- `ros2_ws/src/bonbon_navigation/config/nav2_params.yaml`
- `ros2_ws/src/bonbon_navigation/config/rtabmap_params.yaml`
- `ros2_ws/src/bonbon_speech/bonbon_speech/config/speech_params.yaml`
- `ros2_ws/src/bonbon_tts/config/tts_params.yaml`
- `ros2_ws/src/bonbon_vision/bonbon_vision/config/vision_params.yaml`
- `ros2_ws/src/bonbon_hal/bonbon_hal/config/hal_params.yaml`
- `ros2_ws/src/bonbon_data_stores/config/data_store_params.yaml`
- `ros2_ws/src/bonbon_operator_api/config/operator_api_params.yaml`
- `ros2_ws/src/bonbon_simulation/config/simulation_params.yaml`

## Environment Configs

Deployment environments live under `devops/config/<environment>/`.

Supported environments:

- `local_dev`
- `simulation`
- `lab_robot`
- `staging_robot`
- `production_robot`

Each environment should include:

- `runtime.env`: non-secret runtime variables
- `services.yaml`: service requirements and safety policy metadata
- `models.manifest`: model artifacts required for robot environments

Validate config:

```bash
python devops/scripts/validate_config.py --env simulation
python devops/scripts/validate_config.py --env production_robot --require-runtime-secrets
```

## Runtime Secrets

Runtime secrets are never committed.

Required dashboard/runtime secrets:

- `BONBON_JWT_SECRET`
- `BONBON_ADMIN_PASSWORD`

Keep them in robot-local `/etc/bonbon/bonbon.env`, CI secrets, or a future secret manager.

## Data and Artifact Paths

Common runtime paths:

- `/etc/bonbon`: runtime config
- `/var/lib/bonbon`: database and persistent state
- `/var/log/bonbon`: logs
- `/opt/bonbon/models`: model files
- `/opt/bonbon/maps`: navigation maps
- `/var/lib/bonbon/safety_incidents.db`: safety incident log
- `/var/lib/bonbon/rtabmap.db`: RTAB-Map database

## Simulation Config

Simulation scenarios live in `ros2_ws/src/bonbon_simulation/scenarios/*.yaml`.

Each scenario declares:

- world
- seed
- start and goal
- entities
- timed events
- validation criteria

Use deterministic seeds for repeatable CI.
