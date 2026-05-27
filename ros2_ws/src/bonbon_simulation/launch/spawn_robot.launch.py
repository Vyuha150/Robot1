from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_sim = FindPackageShare("bonbon_simulation")
    xacro_file = PathJoinSubstitution(
        [pkg_sim, "models", "bonbon_robot", "urdf", "bonbon_robot.urdf.xacro"]
    )
    robot_description = Command(["xacro ", xacro_file])

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("x", default_value="0.0"),
            DeclareLaunchArgument("y", default_value="0.0"),
            DeclareLaunchArgument("yaw", default_value="0.0"),
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                name="robot_state_publisher",
                output="screen",
                parameters=[
                    {
                        "robot_description": robot_description,
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                    }
                ],
            ),
            Node(
                package="gazebo_ros",
                executable="spawn_entity.py",
                name="spawn_bonbon",
                output="screen",
                arguments=[
                    "-entity",
                    "bonbon",
                    "-topic",
                    "robot_description",
                    "-x",
                    LaunchConfiguration("x"),
                    "-y",
                    LaunchConfiguration("y"),
                    "-Y",
                    LaunchConfiguration("yaw"),
                ],
            ),
        ]
    )
