# Rollback Process

Rollback uses `/opt/bonbon/releases/<version>` and the `/opt/bonbon/current` symlink on the robot.

Dry run:

```bash
BONBON_DRY_RUN=1 BONBON_ROBOT_HOST=robot.local devops/scripts/rollback_robot.sh previous-version
```

Real rollback:

```bash
BONBON_ROBOT_HOST=robot.local devops/scripts/rollback_robot.sh previous-version
```

Rollback must be available before deployment starts. Failed health checks after deployment should trigger rollback.
