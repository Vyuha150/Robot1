"""nav_pi_edge.launch.py — Edge AI Runtime brief Phase 10. Navigation/
Safety Pi (Pi-3) launch: just the existing, already-tested full Pi-3
bringup (bonbon_navigation_bringup). This brief's edge-ai work does not
add any new Pi-3 node -- Pi-3 already runs the safety_supervisor/
safety_gate/motion_approval_gateway/navigation stack this brief's Phase
7 fixes (GAP-E1/E2/E5) live inside; there is nothing edge-ai-specific to
compose here beyond ensuring those existing fixes are what actually
ships.

ALSO launches hardware_telemetry_node with pi_role=navigation_safety_pi
-- this is the ONE Pi where wheel/stepper/servo/battery HAL state
actually exists (see navigation_bringup.launch.py's own HAL scoping
above), so this is the only Pi role where the node's wheel/joint/
battery subscriptions activate; CPU/memory/disk sampling runs here too,
same as on the other two Pis.

ALSO launches network_monitor_node -- Pi-3 is the chrony NTP server
for pi1/pi2 (config/distributed/robot_network.yaml's time_sync.server),
but chronyd still tracks its own discipline against whatever upstream
source IT syncs to, so monitoring here confirms the server itself
hasn't silently drifted, not just the two clients.

Usage:
  ros2 launch launch/edge_ai/nav_pi_edge.launch.py driver_mode:=real
  ros2 launch launch/edge_ai/nav_pi_edge.launch.py   # mock, dev/CI
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from launch import LaunchDescription


def _include(pkg: str, launch_file: str, launch_arguments: dict | None = None):
    path = os.path.join(get_package_share_directory(pkg), "launch", launch_file)
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path),
        launch_arguments=(launch_arguments or {}).items(),
    )


def generate_launch_description() -> LaunchDescription:
    navigation = _include(
        "bonbon_navigation_bringup",
        "navigation_bringup.launch.py",
        {
            "driver_mode": LaunchConfiguration("driver_mode"),
            "simulation": LaunchConfiguration("simulation"),
        },
    )

    hardware_telemetry = Node(
        package="bonbon_hardware_telemetry",
        executable="hardware_telemetry_node",
        name="hardware_telemetry_node",
        namespace="",
        parameters=[
            {
                "pi_role": "navigation_safety_pi",
                "publish_interval_sec": LaunchConfiguration(
                    "hardware_telemetry_publish_interval_sec"
                ),
            }
        ],
        output="screen",
    )

    network_monitor = Node(
        package="bonbon_distributed_network_monitor",
        executable="network_monitor_node",
        name="network_monitor_node",
        namespace="",
        parameters=[{"pi_role": "navigation_safety_pi"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "driver_mode", default_value="mock", description="real|mock — HAL driver mode"
            ),
            DeclareLaunchArgument(
                "simulation",
                default_value="false",
                description="Set true to enable MockGPIO in bonbon_safety's estop_node",
            ),
            DeclareLaunchArgument(
                "hardware_telemetry_publish_interval_sec",
                default_value="2.0",
                description="How often hardware_telemetry_node republishes dashboard status",
            ),
            navigation,
            hardware_telemetry,
            network_monitor,
        ]
    )
