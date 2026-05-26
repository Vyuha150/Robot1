"""
bonbon_navigation — Localization-only launch file.

Launches:
  - Map server (static map from YAML)
  - RTAB-Map in localization mode (no new nodes added to graph)
  - AMCL as optional fallback localizer

Does NOT launch the full Nav2 navigation stack — for that use navigation.launch.py.
Useful for verifying localization quality before enabling autonomous nav.

Usage::

  ros2 launch bonbon_navigation localization.launch.py \\
      map:=/path/to/cafe_map.yaml \\
      rtabmap_db:=/var/lib/bonbon/rtabmap.db
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_nav = FindPackageShare("bonbon_navigation")

    declare_args = [
        DeclareLaunchArgument(
            "map",
            default_value=PathJoinSubstitution([pkg_nav, "maps", "cafe_map.yaml"]),
            description="Full path to the map YAML file.",
        ),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation clock.",
        ),
        DeclareLaunchArgument(
            "rtabmap_db",
            default_value="/var/lib/bonbon/rtabmap.db",
            description="Path to the RTAB-Map database.",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="Log level.",
        ),
        DeclareLaunchArgument(
            "use_amcl",
            default_value="false",
            description="Also launch AMCL for comparison / fallback.",
        ),
        DeclareLaunchArgument(
            "nav2_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "nav2_params.yaml"]),
            description="Nav2 parameters file (for AMCL config).",
        ),
        DeclareLaunchArgument(
            "rtabmap_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "rtabmap_params.yaml"]),
            description="RTAB-Map parameters file.",
        ),
    ]

    use_sim_time   = LaunchConfiguration("use_sim_time")
    map_yaml       = LaunchConfiguration("map")
    rtabmap_db     = LaunchConfiguration("rtabmap_db")
    log_level      = LaunchConfiguration("log_level")
    nav2_params    = LaunchConfiguration("nav2_params_file")
    rtabmap_params = LaunchConfiguration("rtabmap_params_file")

    # Static map server
    map_server_node = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        output="screen",
        parameters=[
            nav2_params,
            {"use_sim_time": use_sim_time, "yaml_filename": map_yaml},
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # Lifecycle manager for map_server (+ optionally amcl)
    lifecycle_manager = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_localization",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": True,
                "node_names": ["map_server", "amcl"],
                "bond_timeout": 4.0,
            }
        ],
        condition=IfCondition(LaunchConfiguration("use_amcl")),
    )

    lifecycle_manager_no_amcl = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_localization",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "autostart": True,
                "node_names": ["map_server"],
                "bond_timeout": 4.0,
            }
        ],
        condition=__import__("launch.conditions", fromlist=["UnlessCondition"]).UnlessCondition(
            LaunchConfiguration("use_amcl")
        ),
    )

    # AMCL (optional)
    amcl_node = Node(
        package="nav2_amcl",
        executable="amcl",
        name="amcl",
        output="screen",
        parameters=[nav2_params, {"use_sim_time": use_sim_time}],
        arguments=["--ros-args", "--log-level", log_level],
        condition=IfCondition(LaunchConfiguration("use_amcl")),
    )

    # RTAB-Map odometry
    rtabmap_odom_node = Node(
        package="rtabmap_odom",
        executable="icp_odometry",
        name="rtabmap_odom",
        output="screen",
        parameters=[
            rtabmap_params,
            {"use_sim_time": use_sim_time, "publish_tf": True},
        ],
        remappings=[("scan", "/scan"), ("odom", "/odom")],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # RTAB-Map in localization mode
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
                "Mem/IncrementalMemory": "false",
                "Mem/InitWMWithAllNodes": "true",
            },
        ],
        remappings=[
            ("scan", "/scan"),
            ("odom", "/odom"),
            ("map", "/map"),
            ("grid_map", "/map"),
            ("localization_pose", "/rtabmap/localization_pose"),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    return LaunchDescription(
        declare_args
        + [
            map_server_node,
            lifecycle_manager,
            lifecycle_manager_no_amcl,
            amcl_node,
            rtabmap_odom_node,
            rtabmap_node,
        ]
    )
