# Setup

## Prerequisites

Target runtime:

- Ubuntu 22.04
- ROS2 Humble
- Python 3.11+
- Docker and Docker Compose plugin
- `colcon`
- `rosdep`

Development on Windows can run many pure Python tests through the local virtualenv, but ROS2/Gazebo/colcon flows should run in Ubuntu 22.04 or CI.

## Clone and Prepare

```bash
git clone <repo-url> bonbon_robot_ai
cd bonbon_robot_ai
cp .env.example .env
```

Do not commit `.env`.

## Install Dependencies

```bash
devops/scripts/install_dependencies.sh
```

## Build ROS2 Workspace

```bash
cd ros2_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y --rosdistro humble
colcon build --symlink-install
source install/setup.bash
```

## Run Package Tests

```bash
cd ros2_ws/src/bonbon_operator_api
python -m pytest tests/ -q

cd ../bonbon_data_stores
python -m pytest tests/ -q
```

## Run Simulation Smoke

```bash
cd ros2_ws/src/bonbon_simulation
python -m pytest tests/test_simulation_suite.py::test_ci_headless_run -q
```

## Run DevOps Tests

```bash
python -m pytest devops/tests -q
```

## Start Local Docker Dev Stack

```bash
docker compose -f docker-compose.dev.yml up --build
```
