"""
bonbon_navigation — SLAM mode launch file.

Launches RTAB-Map in incremental SLAM mode (builds the map while driving).
Does NOT launch Nav2 autonomous navigation — use teleoperation to drive
the robot and build the map, then switch to localization.launch.py.

Usage::

  ros2 launch bonbon_navigation slam.launch.py use_sim_time:=false
  # Drive robot with teleoperation
  # Save map when done:
  ros2 service call /rtabmap/trigger_new_map std_srvs/srv/Empty
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    pkg_nav = FindPackageShare("bonbon_navigation")

    declare_args = [
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation clock.",
        ),
        DeclareLaunchArgument(
            "rtabmap_db",
            default_value="/var/lib/bonbon/rtabmap.db",
            description="Path to the RTAB-Map database file.",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="Log level.",
        ),
        DeclareLaunchArgument(
            "rtabmap_params_file",
            default_value=PathJoinSubstitution([pkg_nav, "config", "rtabmap_params.yaml"]),
            description="Path to the RTAB-Map parameters YAML.",
        ),
        DeclareLaunchArgument(
            "visualize",
            default_value="false",
            description="Launch rtabmapviz for real-time visualization.",
        ),
    ]

    use_sim_time   = LaunchConfiguration("use_sim_time")
    rtabmap_db     = LaunchConfiguration("rtabmap_db")
    log_level      = LaunchConfiguration("log_level")
    rtabmap_params = LaunchConfiguration("rtabmap_params_file")

    # RTAB-Map odometry (scan-based)
    rtabmap_odom_node = Node(
        package="rtabmap_odom",
        executable="icp_odometry",
        name="rtabmap_odom",
        output="screen",
        parameters=[
            rtabmap_params,
            {
                "use_sim_time": use_sim_time,
                "frame_id": "base_link",
                "odom_frame_id": "odom",
                "publish_tf": True,
            },
        ],
        remappings=[
            ("scan", "/scan"),
            ("odom", "/odom"),
        ],
        arguments=["--ros-args", "--log-level", log_level],
    )

    # RTAB-Map SLAM node (incremental map building)
    rtabmap_slam_node = Node(
        package="rtabmap_slam",
        executable="rtabmap",
        name="rtabmap",
        output="screen",
        parameters=[
            rtabmap_params,
            {
                "use_sim_time": use_sim_time,
                "database_path": rtabmap_db,
                # SLAM mode — incremental memory ON
                "Mem/IncrementalMemory": "true",
                "Mem/InitWMWithAllNodes": "false",
            },
        ],
        remappings=[
            ("scan", "/scan"),
            ("odom", "/odom"),
            ("map", "/map"),
            ("grid_map", "/map"),
        ],
        arguments=["--delete_db_on_start", "--ros-args", "--log-level", log_level],
    )

    # Optional: rtabmapviz for visualization
    rtabmapviz_node = Node(
        package="rtabmap_viz",
        executable="rtabmapviz",
        name="rtabmapviz",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time}],
        remappings=[
            ("scan", "/scan"),
            ("odom", "/odom"),
            ("mapData", "/rtabmap/mapData"),
        ],
        condition=__import__("launch.conditions", fromlist=["IfCondition"]).IfCondition(
            LaunchConfiguration("visualize")
        ),
    )

    # Map saver — publishes occupancy grid to /map for Nav2
    map_server_node = Node(
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        output="screen",
        parameters=[
            {
                "use_sim_time": use_sim_time,
                "yaml_filename": "",  # not loading a map — RTAB-Map provides /map
                "topic_name": "map",
                "frame_id": "map",
            }
        ],
    )

    return LaunchDescription(
        declare_args
        + [
            rtabmap_odom_node,
            rtabmap_slam_node,
            rtabmapviz_node,
        ]
    )
