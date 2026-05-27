from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_sim = FindPackageShare("bonbon_simulation")
    scenario = LaunchConfiguration("scenario")

    return LaunchDescription(
        [
            DeclareLaunchArgument("scenario", default_value="hospital_corridor_navigation"),
            Node(
                package="bonbon_simulation",
                executable="scenario_runner",
                name="headless_scenario_runner",
                output="screen",
                arguments=[
                    PathJoinSubstitution([pkg_sim, "scenarios", [scenario, ".yaml"]]),
                    "--config",
                    PathJoinSubstitution([pkg_sim, "config", "simulation_params.yaml"]),
                ],
            ),
        ]
    )
