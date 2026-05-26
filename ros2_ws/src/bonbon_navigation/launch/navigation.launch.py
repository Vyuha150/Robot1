"""
bonbon_navigation — Full navigation stack launch file.

Launches:
  1. Nav2 (map_server, amcl, planner_server, controller_server,
            behavior_server, bt_navigator, waypoint_follower,
            velocity_smoother, lifecycle_manager)
  2. RTAB-Map in localization mode
  3. BonBon NavigationNode (LifecycleNode, managed by its own lifecycle_manager)

Usage::

  ros2 launch bonbon_navigation navigation.launch.py \\
      map:=/path/to/cafe_map.yaml \\
      use_sim_time:=false \\
      rtabmap_db:=/var/lib/bonbon/rtabmap.db
"""
from __future__ import annotations

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    EqualsSubstitution,
    LaunchConfiguration,
    PathJoinSubstitution,
    PythonExpression,
)
from launch_ros.actions import (
    LifecycleNode,
    LoadComposableNodes,
    Node,
    PushRosNamespace,
    SetRemap,
)
from launch_ros.substitutions import FindPackageShare
from launch_ros.descriptions import ParameterFile


def generate_launch_description() -> LaunchDescription:
    pkg_nav = FindPackageShare("bonbon_navigation")

    # ── Launch arguments ──────────────────────────────────────────────────────
    declare_args = [
        DeclareLaunchArgument(
            "map",
            default_value=PathJoinSubstitution([pkg_nav, "maps", "cafe_map.yaml"]),
            description="Full path to the map YAML file.",
        ),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation (Gazebo) clock.",
        ),
        DeclareLaunchArgument(
            "rtabmap_db",
            default_value="/var/lib/bonbon/rtabmap.db",
            description="Path to the RTAB-Map database file.",
        ),
        DeclareLaunchArgument(
            "namespace",
            default_value="",
            description="ROS2 namespace for all nodes.",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="Log level: debug | info | warn | error",
        ),
        DeclareLaunchArgument(
            "use_amcl_fallback",
            default_value="false",
            description="Launch AMCL alongside RTAB-Map as fallback.",
        ),
        DeclareLaunchArgument(
            "autostart",
            default_value="true",
            description="Auto-configure and activate lifecycle nodes.",
        ),
        DeclareLaunchArgument(
            "nav2_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "nav2_params.yaml"]),
            description="Path to the Nav2 parameters YAML.",
        ),
        DeclareLaunchArgument(
            "bonbon_nav_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "nav_params.yaml"]),
            description="Path to the BonBon navigation node parameters YAML.",
        ),
        DeclareLaunchArgument(
            "rtabmap_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "rtabmap_params.yaml"]),
            description="Path to the RTAB-Map parameters YAML.",
        ),
    ]

    use_sim_time   = LaunchConfiguration("use_sim_time")
    namespace      = LaunchConfiguration("namespace")
    log_level      = LaunchConfiguration("log_level")
    autostart      = LaunchConfiguration("autostart")
    map_yaml       = LaunchConfiguration("map")
    rtabmap_db     = LaunchConfiguration("rtabmap_db")
    nav2_params    = LaunchConfiguration("nav2_params_file")
    bonbon_params  = LaunchConfiguration("bonbon_nav_params_file")
    rtabmap_params = LaunchConfiguration("rtabmap_params_file")

    # ── Map Server + AMCL lifecycle nodes ────────────────────────────────────
    map_server_node = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[
            nav2_params,
            {"yaml_filename": map_yaml, "use_sim_time": use_sim_time},
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    amcl_node = Node(
        package="nav2_amcl",
        executable="amcl",
        name="amcl",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
        condition=IfCondition(LaunchConfiguration("use_amcl_fallback")),
    )

    # ── Nav2 stack nodes ─────────────────────────────────────────────────────
    planner_server_node = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
    )

    controller_server_node = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        remappings=[("cmd_vel", "cmd_vel_nav")],
        arguments=["--ros-args", "--log-level", log_level],
    )

    smoother_server_node = Node(
        package="nav2_smoother",
        executable="smoother_server",
        name="smoother_server",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
    )

    behavior_server_node = Node(
        package="nav2_behaviors",
        executable="behavior_server",
        name="behavior_server",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        remappings=[("cmd_vel", "cmd_vel_nav")],
        arguments=["--ros-args", "--log-level", log_level],
    )

    bt_navigator_node = Node(
        package="nav2_bt_navigator",
        executable="bt_navigator",
        name="bt_navigator",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
    )

    waypoint_follower_node = Node(
        package="nav2_waypoint_follower",
        executable="waypoint_follower",
        name="waypoint_follower",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
    )

    velocity_smoother_node = Node(
        package="nav2_velocity_smoother",
        executable="velocity_smoother",
        name="velocity_smoother",
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        remappings=[
            ("cmd_vel", "cmd_vel_nav"),
            ("cmd_vel_smoothed", "cmd_vel_smoothed"),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # Nav2 lifecycle manager
    nav2_lifecycle_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_navigation",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": autostart,
                "node_names": [
                    "map_server",
                    "planner_server",
                    "controller_server",
                    "smoother_server",
                    "behavior_server",
                    "bt_navigator",
                    "waypoint_follower",
                    "velocity_smoother",
                ],
                "bond_timeout": 4.0,
                "attempt_respawn_reconnection": True,
            }
        ],
    )

    # ── RTAB-Map (localization mode) ─────────────────────────────────────────
    rtabmap_node = Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        output="screen",
        parameters=[
            rtabmap_params,
            {
                "use_sim_time": use_sim_time,
                "database_path": rtabmap_db,
                "Mem/IncrementalMemory": "false",   # localization mode
                "Mem/InitWMWithAllNodes": "true",
            },
        ],
        remappings=[
            ("scan", "/scan"),
            ("odom", "/odom"),
            ("map", "/map"),
            ("grid_map", "/map"),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # ── BonBon NavigationNode (LifecycleNode) ─────────────────────────────────
    bonbon_nav_node = LifecycleNode(
        package="bonbon_navigation",
        executable="navigation_node",
        name="bonbon_navigation_node",
        namespace=namespace,
        output="screen",
        parameters=[
            bonbon_params,
            {
                "use_sim_time": use_sim_time,
                "map_yaml_path": map_yaml,
            },
        ],
        arguments=["--ros-args", "--log-level", log_level],
        respawn=False,  # Lifecycle manages its own restart
    )

    # BonBon lifecycle manager
    bonbon_lifecycle_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_bonbon_nav",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": autostart,
                "node_names": ["bonbon_navigation_node"],
                "bond_timeout": 4.0,
                "attempt_respawn_reconnection": True,
            }
        ],
    )

    return LaunchDescription(
        declare_args
        + [
            map_server_node,
            amcl_node,
            planner_server_node,
            controller_server_node,
            smoother_server_node,
            behavior_server_node,
            bt_navigator_node,
            waypoint_follower_node,
            velocity_smoother_node,
            nav2_lifecycle_manager,
            rtabmap_node,
            bonbon_nav_node,
            bonbon_lifecycle_manager,
        ]
    )
