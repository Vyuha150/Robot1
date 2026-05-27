# Simulation Overview

`bonbon_simulation` validates BonBon software before hardware deployment. It separates world assets, robot model assets, scenario definitions, deterministic validation logic, and ROS launch files.

Supported environments include hospital corridors, reception areas, patient rooms, hotel lobbies, office hallways, university corridors, mall walkways, homes, charging docks, narrow passages, crowded waiting areas, low-light zones, glass-wall zones, and obstacle-heavy zones.

The headless runner is intentionally deterministic. Full Gazebo or Ignition runs can publish richer telemetry later, but the same pass/fail thresholds and report schema remain the deployment gate.
