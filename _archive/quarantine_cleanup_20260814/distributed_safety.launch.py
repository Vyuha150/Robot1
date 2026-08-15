"""Launches distributed_safety_node with the self_id for THIS Pi.

Usage: ros2 launch bonbon_distributed_safety distributed_safety.launch.py self_id:=pi3
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
        package="bonbon_distributed_safety",
        executable="distributed_safety_node",
        name="distributed_safety_node",
        namespace="",
        parameters=[{"self_id": LaunchConfiguration("self_id")}],
        output="screen",
    )
    return LaunchDescription([self_id_arg, node])
