# ROS2 Interfaces

This page lists the major ROS2 topic, service, and action contracts across the platform.

## Core Sensor Topics

| Topic | Type | Producer | Consumers |
|---|---|---|---|
| `/bonbon/lidar/scan` | `sensor_msgs/LaserScan` | `bonbon_hal` lidar node | safety, navigation/perception |
| `/scan` | `sensor_msgs/LaserScan` | simulation/Nav2 bridge | Nav2, RTAB-Map |
| `/bonbon/imu/data_raw` | `sensor_msgs/Imu` | `bonbon_hal` IMU node | safety |
| `/imu/data` | `sensor_msgs/Imu` | simulation | Nav2/RTAB-Map/simulation checks |
| `/bonbon/temperature/readings` | `bonbon_msgs/ThermalReadings` | HAL IMU/thermal | safety |
| `/bonbon/battery/state` | `sensor_msgs/BatteryState` | battery node/sim | safety, navigation, dashboard |
| `/bonbon/estop/state` | `std_msgs/Bool` | e-stop node | safety, dashboard |
| `/bonbon/bumper/state` | `bonbon_msgs/BumperState` | bumper driver | safety |

## Camera and Vision Topics

| Topic | Type | Notes |
|---|---|---|
| `/bonbon/vision/camera/color/image_raw` | `sensor_msgs/Image` | HAL camera RGB |
| `/bonbon/vision/camera/depth/image_raw` | `sensor_msgs/Image` | HAL camera depth |
| `/bonbon/vision/camera/color/camera_info` | `sensor_msgs/CameraInfo` | camera calibration |
| `/camera/color/image_raw` | `sensor_msgs/Image` | simulation camera RGB |
| `/camera/depth/image_raw` | `sensor_msgs/Image` | simulation depth |
| `/bonbon/vision/objects` | `bonbon_msgs/DetectedObjectArray` | detected objects |
| `/bonbon/vision/persons` | `bonbon_msgs/PersonStateArray` | tracked persons |
| `/bonbon/vision/persons_identified` | `bonbon_msgs/PersonStateArray` | identified persons |

## Safety Topics and Services

| Interface | Type | Direction |
|---|---|---|
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | published by safety supervisor |
| `/bonbon/safety/event` | `bonbon_msgs/SafetyEvent` | published by safety supervisor |
| `/bonbon/safety/critical_node_crashed` | `std_msgs/Bool` | watchdog output |
| `/bonbon/safety/important_node_crashed` | `std_msgs/Bool` | watchdog output |
| `/bonbon/safety/watchdog_node/health` | `bonbon_msgs/ModuleHealth` | watchdog health |
| `/bonbon/safety/reset` | `bonbon_srvs/SafetyReset` | manual reset service |
| `/bonbon/safety_gate/cmd_vel` | `geometry_msgs/Twist` | gated velocity input |

## Navigation Topics, Services, and Actions

| Interface | Type | Notes |
|---|---|---|
| `/navigation/status` | `bonbon_msgs/NavigationStatus` | navigation status |
| `/navigation/goal` | `bonbon_msgs/NavigationGoal` | active goal |
| `/navigation/docking_status` | `bonbon_msgs/DockingStatus` | docking phase |
| `/navigation/recovery_status` | `bonbon_msgs/RecoveryStatus` | recovery state |
| `/navigation/human_costmap` | `nav_msgs/OccupancyGrid` | human-aware local costmap |
| `/health/navigation` | `bonbon_msgs/ModuleHealth` or diagnostic health | navigation health |
| `/navigation/navigate_to` | `bonbon_srvs/NavigateTo` | send goal |
| `/navigation/cancel` | `bonbon_srvs/CancelNavigation` | cancel goal |
| `/navigation/get_nearest_charger` | `bonbon_srvs/GetNearestCharger` | charger lookup |
| `/navigate_to_pose` | Nav2 action | Nav2 goal action |
| `/follow_waypoints` | Nav2 action | Nav2 waypoint action |
| `/map` | `nav_msgs/OccupancyGrid` | map |
| `/odom` | `nav_msgs/Odometry` | odometry |
| `/tf`, `/tf_static` | TF | transforms |

## Speech and TTS Topics

| Topic | Type | Notes |
|---|---|---|
| `/speech/command` | `bonbon_msgs/SpeechCommand` | parsed speech command |
| `/speech/transcription` | `bonbon_msgs/SpeechTranscription` | STT output |
| `/health/speech` | `bonbon_msgs/ModuleHealth` | speech health |
| `/bonbon/tts/request` | `bonbon_msgs/TTSRequest` | TTS request |
| `/bonbon/tts/event` | event/metrics topic | simulation/config contract |

## LLM, Perception AI, and Memory

| Interface | Type | Notes |
|---|---|---|
| `/perception/behavior` | `bonbon_msgs/BehaviorRecommendation` | behavior recommendation |
| `/bonbon/nav/status` | status topic | optional AI input |
| `/bonbon/spatial/pose` | `geometry_msgs/Pose2D` | optional AI input |
| `/bonbon/data_store/health` | `std_msgs/String` | JSON health snapshot |
| `/bonbon/data_store/health_check` | `std_srvs/Trigger` | health service |
| `/bonbon/data_store/create_backup` | `std_srvs/Trigger` | backup service |
| `/bonbon/memory/query` | bridge/service stub | operator API memory path |
| `/bonbon/rag/query` | bridge/service stub | operator API RAG path |

## Health and Fault Interfaces

| Interface | Type | Notes |
|---|---|---|
| `/bonbon/hal/fault` | `bonbon_msgs/HalFault` | HAL fault stream |
| `/bonbon/spatial/lidar_node/health` | `bonbon_msgs/ModuleHealth` | lidar health |
| `/bonbon/spatial/imu_node/health` | `bonbon_msgs/ModuleHealth` | IMU health |
| `/bonbon/vision/camera_node/health` | `bonbon_msgs/ModuleHealth` | camera health |
| `/bonbon/power/battery_node/health` | `bonbon_msgs/ModuleHealth` | battery health |
| `/bonbon/safety/estop_node/health` | `bonbon_msgs/ModuleHealth` | e-stop health |

## Interface Compatibility Rules

- Safety topic names are deployment contracts. Do not rename without updating safety tests, simulation tests, dashboard status aggregation, and deployment health checks.
- Store/RAG interface changes must be checked against `bonbon_operator_api`.
- Motion must never bypass `/bonbon/safety_gate/cmd_vel`.
- Simulation topic aliases such as `/scan`, `/imu/data`, and `/camera/color/image_raw` must be bridged or remapped consistently for Nav2/RTAB-Map.
