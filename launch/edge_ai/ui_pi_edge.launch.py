"""ui_pi_edge.launch.py — Edge AI Runtime brief Phase 10. UI/Supervisor
Pi (Pi-1) launch: just the existing, already-tested full Pi-1 bringup
(bonbon_ui_api_bringup) -- Pi-1 owns no AI/perception/actuation code by
design (see config/distributed/pi_ui_api.yaml's forbidden list), so
there is nothing edge-ai-specific to add here beyond what
bonbon_operator_api's dashboard already serves (Phase 12 extends that
existing REST/WS surface, it does not add a Pi-1-side node).

Usage:
  ros2 launch launch/edge_ai/ui_pi_edge.launch.py
  ros2 launch launch/edge_ai/ui_pi_edge.launch.py port:=8080
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


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

    return LaunchDescription(
        [
            DeclareLaunchArgument("host", default_value="0.0.0.0", description="API server bind host"),
            DeclareLaunchArgument("port", default_value="8080", description="API server port"),
            DeclareLaunchArgument("ros2_enabled", default_value="true", description="Enable ROS2 bridge"),
            ui_api,
        ]
    )
