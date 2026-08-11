"""full_edge_sim.launch.py — Edge AI Runtime brief Phase 10. Single-
machine simulation: composes all three per-Pi edge launch files
(ui_pi_edge, ai_pi_edge, nav_pi_edge) together for local dev/CI, where
one machine plays all three Pi roles instead of the real three-Raspberry-Pi
deployment.

Always forces driver_mode=mock (real HAL drivers assume specific GPIO/
I2C/USB devices that don't exist off-Pi) and simulation=true for the
safety estop node's GPIO mock -- this is the honest dev/CI equivalent of
the real fleet, not a claim that it exercises real hardware.

Usage:
  ros2 launch launch/edge_ai/full_edge_sim.launch.py
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def _include_this_dir(launch_file: str, launch_arguments: dict | None = None):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), launch_file)
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path),
        launch_arguments=(launch_arguments or {}).items(),
    )


def generate_launch_description() -> LaunchDescription:
    ui_pi = _include_this_dir("ui_pi_edge.launch.py")
    ai_pi = _include_this_dir("ai_pi_edge.launch.py", {"driver_mode": "mock"})
    nav_pi = _include_this_dir("nav_pi_edge.launch.py", {"driver_mode": "mock", "simulation": "true"})

    return LaunchDescription([ui_pi, ai_pi, nav_pi])
