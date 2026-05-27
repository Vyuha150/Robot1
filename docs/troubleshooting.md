# Troubleshooting

## ROS2 Workspace Fails To Build

Check dependencies:

```bash
rosdep update
rosdep install --from-paths ros2_ws/src --ignore-src -r -y --rosdistro humble
```

Build with verbose output:

```bash
cd ros2_ws
colcon build --symlink-install --event-handlers console_direct+
```

## Safety State Does Not Publish

Check launch:

```bash
ros2 launch bonbon_safety safety.launch.py simulation:=true
ros2 topic echo /bonbon/safety/state
```

Check dependencies:

```bash
ros2 topic echo /bonbon/estop/state
ros2 topic echo /bonbon/battery/state
ros2 topic echo /bonbon/lidar/scan
ros2 topic echo /bonbon/imu/data_raw
```

## Robot Will Not Move

Inspect safety and command path:

```bash
ros2 topic echo /bonbon/safety/state
ros2 topic echo /bonbon/safety_gate/cmd_vel
ros2 topic echo /cmd_vel
```

Common causes:

- e-stop active
- safety state is `SAFE_STOP`, `FAULT`, or `DANGER`
- missing safety heartbeat
- navigation publishes to wrong topic
- Nav2 lifecycle inactive

## Navigation Fails

Check:

```bash
ros2 topic echo /map --once
ros2 topic echo /odom --once
ros2 topic echo /tf
ros2 service list | grep navigation
```

Common causes:

- map file path invalid
- RTAB-Map database missing
- Nav2 lifecycle inactive
- localization covariance too high
- obstacle blocks path and recovery exhausted

## Speech or TTS Fails

Check:

```bash
ros2 topic echo /speech/command
ros2 topic echo /speech/transcription
ros2 topic echo /bonbon/tts/request
ros2 topic echo /health/speech
```

Common causes:

- microphone driver unavailable
- STT model missing
- TTS backend missing
- audio device permission issue

## Operator API Fails To Start

Check runtime secrets:

```bash
echo "$BONBON_JWT_SECRET"
echo "$BONBON_ADMIN_PASSWORD"
```

Do not print real secrets on shared terminals. Use this only on a secure robot shell.

Check API health:

```bash
curl http://localhost:8080/health
```

## Data Store Fails

Check paths and permissions:

```bash
echo "$BONBON_DATA_DIR"
ls -lah /var/lib/bonbon
ros2 topic echo /bonbon/data_store/health
```

Common causes:

- SQLite database path not writable
- backup directory missing
- vector/RAG model dependency missing

## Simulation Scenario Fails

Run one scenario directly:

```bash
cd ros2_ws/src/bonbon_simulation
python -m bonbon_simulation.core.runner scenarios/hospital_corridor_navigation.yaml --config config/simulation_params.yaml
```

Inspect generated reports under:

- `simulation_reports/`
- `simulation_artifacts/`

## Deployment Fails

Validate config:

```bash
python devops/scripts/validate_config.py --env lab_robot
```

Run dry-run checks:

```bash
python devops/scripts/pre_deploy_check.py --dry-run
python devops/scripts/post_deploy_check.py --dry-run
```

Collect logs:

```bash
devops/scripts/collect_logs.sh
```
