# CI Simulation Guide

Use the deterministic headless tests for fast CI:

```bash
cd ros2_ws/src/bonbon_simulation
python -m pytest tests/ -q
```

For ROS-enabled CI, add a second job that launches:

```bash
ros2 launch bonbon_simulation headless_ci.launch.py scenario:=hospital_corridor_navigation
```

Recommended deployment gate:

- all `bonbon_simulation` tests pass
- touched package tests pass
- safety gate tests pass when safety or bridge code changes
- scenario reports archived as CI artifacts
