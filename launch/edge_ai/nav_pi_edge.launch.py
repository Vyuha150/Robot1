"""nav_pi_edge.launch.py — Edge AI Runtime brief Phase 10. Navigation/
Safety Pi (Pi-3) launch: just the existing, already-tested full Pi-3
bringup (bonbon_navigation_bringup). This brief's edge-ai work does not
add any new Pi-3 node -- Pi-3 already runs the safety_supervisor/
safety_gate/motion_approval_gateway/navigation stack this brief's Phase
7 fixes (GAP-E1/E2/E5) live inside; there is nothing edge-ai-specific to
compose here beyond ensuring those existing fixes are what actually
ships.

Usage:
  ros2 launch launch/edge_ai/nav_pi_edge.launch.py driver_mode:=real
  ros2 launch launch/edge_ai/nav_pi_edge.launch.py   # mock, dev/CI
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
    navigation = _include(
        "bonbon_navigation_bringup",
        "navigation_bringup.launch.py",
        {
            "driver_mode": LaunchConfiguration("driver_mode"),
            "simulation": LaunchConfiguration("simulation"),
        },
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("driver_mode", default_value="mock", description="real|mock — HAL driver mode"),
            DeclareLaunchArgument(
                "simulation",
                default_value="false",
                description="Set true to enable MockGPIO in bonbon_safety's estop_node",
            ),
            navigation,
        ]
    )
