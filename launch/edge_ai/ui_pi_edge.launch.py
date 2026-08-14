"""ui_pi_edge.launch.py — Edge AI Runtime brief Phase 10. UI/Supervisor
Pi (Pi-1) launch: just the existing, already-tested full Pi-1 bringup
(bonbon_ui_api_bringup) -- Pi-1 owns no AI/perception/actuation code by
design (see config/distributed/pi_ui_api.yaml's forbidden list), so
there is nothing edge-ai-specific to add here beyond what
bonbon_operator_api's dashboard already serves (Phase 12 extends that
existing REST/WS surface, it does not add a Pi-1-side node).

PLUS hardware_telemetry_node with pi_role=ui_supervisor_pi -- this Pi
has no HAL hardware, so the node's own pi_role gating (see
bonbon_hardware_telemetry.nodes.hardware_telemetry_node's docstring)
means it only samples this Pi's own CPU/memory/disk, same as on every
other Pi.

PLUS network_monitor_node -- every Pi runs its own local chrony
offset check (see bonbon_distributed_network_monitor's own docstring),
not just the ones with HAL hardware.

Usage:
  ros2 launch launch/edge_ai/ui_pi_edge.launch.py
  ros2 launch launch/edge_ai/ui_pi_edge.launch.py port:=8080
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
    ui_api = _include(
        "bonbon_ui_api_bringup",
        "ui_api_bringup.launch.py",
        {
            "host": LaunchConfiguration("host"),
            "port": LaunchConfiguration("port"),
            "ros2_enabled": LaunchConfiguration("ros2_enabled"),
        },
    )

    hardware_telemetry = Node(
        package="bonbon_hardware_telemetry",
        executable="hardware_telemetry_node",
        name="hardware_telemetry_node",
        namespace="",
        parameters=[
            {
                "pi_role": "ui_supervisor_pi",
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
        parameters=[{"pi_role": "ui_supervisor_pi"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "host", default_value="0.0.0.0", description="API server bind host"
            ),
            DeclareLaunchArgument("port", default_value="8080", description="API server port"),
            DeclareLaunchArgument(
                "ros2_enabled", default_value="true", description="Enable ROS2 bridge"
            ),
            DeclareLaunchArgument(
                "hardware_telemetry_publish_interval_sec",
                default_value="2.0",
                description="How often hardware_telemetry_node republishes dashboard status",
            ),
            ui_api,
            hardware_telemetry,
            network_monitor,
        ]
    )
