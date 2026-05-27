# ROS2 Interfaces

The deployment system does not define robot behavior, but it validates that the runtime exposes the expected ROS2 interfaces.

## Required Sensor Topics

Post-deployment checks expect these topics to exist:

- `/scan`: simulated or hardware RPLIDAR
- `/imu/data`: IMU readings
- `/camera/color/image_raw`: RGB camera
- `/bonbon/battery/state`: battery state
- `/bonbon/estop/state`: emergency stop state

## Safety Interfaces

Expected safety services and topics:

- `/bonbon/safety/state`
- `/bonbon/safety/event`
- `/bonbon/safety/reset`
- `/bonbon/safety_gate/cmd_vel`

Deployment must not bypass the safety gate. Navigation containers should publish motion through the safety-gated velocity path.

## Navigation Interfaces

Expected navigation stack interfaces:

- Nav2 action servers from `nav2_bringup`
- `/navigate_to_pose`: Nav2 NavigateToPose action
- `/follow_waypoints`: Nav2 FollowWaypoints action when waypoint follower is enabled
- `/map`
- `/odom`
- `/tf`
- `/tf_static`
- `/navigation/docking_status`

## Service Interfaces

Expected service families:

- `/bonbon/safety/reset`: safety reset
- `/bonbon/navigation/cancel`: navigation cancellation when exposed by the navigation package
- `/bonbon/memory/query`: operator API memory query bridge
- `/bonbon/rag/query`: operator API RAG query bridge

## Dashboard Interfaces

The dashboard API must expose:

- `GET /health`
- authenticated command endpoints
- metrics endpoint for Prometheus scraping when enabled

## Observability Metrics

Prometheus expects exporters or app metrics for:

- `bonbon_ros2_node_health`
- `bonbon_safety_events_total`
- `bonbon_navigation_failures_total`
- `bonbon_tts_latency_seconds_bucket`
- `bonbon_stt_latency_seconds_bucket`
- `bonbon_perception_latency_seconds_bucket`
- `bonbon_llm_latency_seconds_bucket`
- `bonbon_actuation_errors_total`
- `bonbon_battery_percentage`
- `bonbon_emergency_stop_events_total`
- `bonbon_deployment_version_info`
