# Troubleshooting

If Docker build fails, inspect the image-specific Dockerfile under `deployment/docker/`.

If ROS2 build fails, run:

```bash
devops/scripts/build_ros2.sh
```

If deployment fails before copying artifacts, run config validation:

```bash
python3 devops/scripts/validate_config.py --env lab_robot
```

If services fail after deployment:

```bash
devops/scripts/health_check.sh
devops/scripts/collect_logs.sh
```

If rollback fails, confirm `/opt/bonbon/releases/<version>` exists on the robot.
