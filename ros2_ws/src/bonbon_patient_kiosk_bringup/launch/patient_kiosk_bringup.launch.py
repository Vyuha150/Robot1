"""patient_kiosk_bringup.launch.py — full bringup for the patient kiosk screen.

Composes bonbon_patient_kiosk's own launch file. Launches no new node
types itself -- this file is composition only, mirroring
bonbon_ui_api_bringup's pattern.

Runs on its own screen/host, separate from Pi-1's bonbon_ui_api_bringup
(staff dashboard) -- see the package README for why. If a deployment adds
cross-Pi liveness/authority nodes for this host, that is a topology
decision for that deployment's own bringup, not assumed here.

Usage:
  ros2 launch bonbon_patient_kiosk_bringup patient_kiosk_bringup.launch.py
  ros2 launch bonbon_patient_kiosk_bringup patient_kiosk_bringup.launch.py port:=8090
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
    kiosk_api = _include(
        "bonbon_patient_kiosk",
        "kiosk_api.launch.py",
        {
            "host": LaunchConfiguration("host"),
            "port": LaunchConfiguration("port"),
            "ros2_enabled": LaunchConfiguration("ros2_enabled"),
        },
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("host", default_value="0.0.0.0", description="API server bind host"),
            DeclareLaunchArgument("port", default_value="8090", description="API server port"),
            DeclareLaunchArgument("ros2_enabled", default_value="true", description="Enable ROS2 bridge"),
            kiosk_api,
        ]
    )
