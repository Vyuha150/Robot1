# Examples

## Build Everything

```bash
cd ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

## Launch Safety Stack

```bash
ros2 launch bonbon_safety safety.launch.py simulation:=true
```

## Launch Navigation

```bash
ros2 launch bonbon_navigation navigation.launch.py \
  use_sim_time:=false \
  map:=$(ros2 pkg prefix bonbon_navigation)/share/bonbon_navigation/maps/cafe_map.yaml \
  rtabmap_db:=/var/lib/bonbon/rtabmap.db
```

## Send Navigation Goal

```bash
ros2 service call /navigation/navigate_to bonbon_srvs/srv/NavigateTo \
  '{goal_id: "table_5", named_location: "table_5", timeout_sec: 60.0, enqueue: false}'
```

## Cancel Navigation

```bash
ros2 service call /navigation/cancel bonbon_srvs/srv/CancelNavigation \
  '{goal_id: "", cancel_all: true, reason: "operator requested pause"}'
```

## Safety Reset

```bash
ros2 service call /bonbon/safety/reset bonbon_srvs/srv/SafetyReset \
  "{operator_id: 'ops_001', reason: 'Obstacle cleared and robot inspected'}"
```

## Inspect Safety

```bash
ros2 topic echo /bonbon/safety/state
ros2 topic echo /bonbon/safety/event
ros2 topic echo /bonbon/estop/state
```

## Run Simulation Scenario

```bash
cd ros2_ws/src/bonbon_simulation
python -m bonbon_simulation.core.runner \
  scenarios/hospital_corridor_navigation.yaml \
  --config config/simulation_params.yaml
```

## Run DevOps Validation

```bash
python -m pytest devops/tests -q
python devops/scripts/validate_config.py --env simulation
python devops/scripts/pre_deploy_check.py --dry-run
python devops/scripts/post_deploy_check.py --dry-run
```

## Start Simulation Compose Stack

```bash
docker compose -f docker-compose.simulation.yml up --build
```

## Generate Release Metadata

```bash
python devops/scripts/release_version.py --channel staging
```

## Verify Release Checksum

```bash
python devops/scripts/verify_release.py \
  --artifact bonbon-release.tar.gz \
  --sha256 bonbon-release.tar.gz.sha256
```

## Deployment Dry Run

```bash
BONBON_DRY_RUN=1 \
BONBON_ROBOT_HOST=robot.local \
BONBON_ROBOT_USER=bonbon \
devops/scripts/deploy_to_robot.sh --env lab_robot --version lab-test --dry-run
```
