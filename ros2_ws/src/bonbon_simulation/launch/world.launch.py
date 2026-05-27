from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_sim = FindPackageShare("bonbon_simulation")
    world_path = PathJoinSubstitution([pkg_sim, "worlds", [LaunchConfiguration("world"), ".world"]])
    headless = LaunchConfiguration("headless")

    return LaunchDescription([
        DeclareLaunchArgument("world", default_value="hospital_corridor"),
        DeclareLaunchArgument("headless", default_value="true"),
        ExecuteProcess(
            cmd=["gzserver", world_path],
            output="screen",
            condition=IfCondition(headless),
        ),
        ExecuteProcess(
            cmd=["gazebo", "--verbose", world_path],
            output="screen",
            condition=UnlessCondition(headless),
        ),
    ])
