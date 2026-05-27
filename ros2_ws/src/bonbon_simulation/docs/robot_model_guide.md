# Robot Model Guide

The simulated BonBon robot is defined in `models/bonbon_robot/urdf/bonbon_robot.urdf.xacro`.

It includes:

- differential drive base
- configurable footprint and dimensions
- wheel joints
- torso and head links
- head pan servo joint
- RPLIDAR frame
- IMU frame
- RGB/depth camera frame
- microphone frame
- speaker frame
- collision geometry

Robot dimensions are configured in `config/simulation_params.yaml` and flow into `RobotSpawnManager` for validation.
