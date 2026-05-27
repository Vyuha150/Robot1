# Gazebo and Isaac Options

Gazebo Classic is supported through `world.launch.py`, `spawn_robot.launch.py`, and `simulation.launch.py`.

Ignition/Gazebo compatibility is represented by SDF 1.9 world files and the `WorldLauncher` planning API. The deterministic runner does not require either simulator, which keeps CI fast and stable.

Isaac Sim compatibility is intentionally asset-oriented:

- worlds are isolated under `worlds/`
- robot geometry is isolated under `models/bonbon_robot/`
- entities are isolated under `models/entities/`
- scenario semantics live in YAML and can be reused by an Isaac adapter

Future USD export should preserve scenario names, seeds, entity names, event timestamps, and pass/fail criteria.
