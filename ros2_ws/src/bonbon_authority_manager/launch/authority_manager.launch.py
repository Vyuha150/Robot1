"""Launches authority_manager_node with the self_id for THIS Pi.

Usage: ros2 launch bonbon_authority_manager authority_manager.launch.py self_id:=pi1
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def generate_launch_description() -> LaunchDescription:
    self_id_arg = DeclareLaunchArgument(
        "self_id",
        default_value="pi3",
        description="Which Pi this instance runs on: pi1 | pi2 | pi3",
    )
    node = LifecycleNode(
        package="bonbon_authority_manager",
        executable="authority_manager_node",
        name="authority_manager_node",
        namespace="",
        parameters=[{"self_id": LaunchConfiguration("self_id")}],
        output="screen",
    )
    return LaunchDescription([self_id_arg, node])
