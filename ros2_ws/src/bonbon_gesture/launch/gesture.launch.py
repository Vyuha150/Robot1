"""
gesture.launch.py
=================
Launch file for the bonbon_gesture gesture recognition node.
Loads gesture.yaml parameters and starts the GestureNode lifecycle node.
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("bonbon_gesture")
    default_config = os.path.join(pkg_share, "config", "gesture.yaml")

    config_arg = DeclareLaunchArgument(
        "config_file",
        default_value=default_config,
        description="Full path to the gesture YAML parameters file.",
    )

    backend_arg = DeclareLaunchArgument(
        "backend",
        default_value="mediapipe",
        description="Gesture backend to use: mediapipe or mock.",
    )

    gesture_node = LifecycleNode(
        package="bonbon_gesture",
        executable="gesture_node",
        name="gesture_node",
        namespace="bonbon",
        parameters=[
            LaunchConfiguration("config_file"),
            {"backend": LaunchConfiguration("backend")},
        ],
        output="screen",
    )

    return LaunchDescription([
        config_arg,
        backend_arg,
        gesture_node,
    ])
