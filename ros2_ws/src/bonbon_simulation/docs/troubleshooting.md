# Troubleshooting

If `gzserver` is missing, run the deterministic pytest suite first and install Gazebo packages before full simulation.

If scenarios are flaky, check that the scenario has a fixed `seed` and no wall-clock timing dependency.

If reports are missing, confirm that `report_dir` and `artifact_dir` are writable.

If a robot fails to spawn, validate the xacro:

```bash
xacro models/bonbon_robot/urdf/bonbon_robot.urdf.xacro
```

If Nav2 does not move, confirm `/bonbon/safety_gate/cmd_vel` is connected and safety state permits motion.
