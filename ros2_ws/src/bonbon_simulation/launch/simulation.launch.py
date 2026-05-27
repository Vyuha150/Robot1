from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_sim = FindPackageShare("bonbon_simulation")
    pkg_nav = FindPackageShare("bonbon_navigation")
    world = LaunchConfiguration("world")
    headless = LaunchConfiguration("headless")
    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument("world", default_value="hospital_corridor"),
            DeclareLaunchArgument("headless", default_value="true"),
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("scenario", default_value="hospital_corridor_navigation"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([pkg_sim, "launch", "world.launch.py"])
                ),
                launch_arguments={"world": world, "headless": headless}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([pkg_sim, "launch", "spawn_robot.launch.py"])
                ),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution([pkg_nav, "launch", "navigation.launch.py"])
                ),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            Node(
                package="bonbon_simulation",
                executable="scenario_runner",
                name="simulation_scenario_runner",
                output="screen",
                arguments=[
                    PathJoinSubstitution(
                        [pkg_sim, "scenarios", [LaunchConfiguration("scenario"), ".yaml"]]
                    ),
                    "--config",
                    PathJoinSubstitution([pkg_sim, "config", "simulation_params.yaml"]),
                ],
            ),
        ]
    )
