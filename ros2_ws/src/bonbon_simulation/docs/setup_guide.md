# Setup Guide

Build from the ROS2 workspace root:

```bash
colcon build --packages-select bonbon_simulation
source install/setup.bash
```

Run tests:

```bash
cd ros2_ws/src/bonbon_simulation
python -m pytest tests/ -q
```

Full simulation needs ROS2 Humble plus Gazebo Classic or Ignition/Gazebo packages, Nav2, RTAB-Map, `gazebo_ros`, `ros_gz_sim`, and `ros_gz_bridge`.

Isaac Sim compatibility is structural: robot, world, scenario, and entity assets are separated so USD conversion can be added without changing scenario semantics.
