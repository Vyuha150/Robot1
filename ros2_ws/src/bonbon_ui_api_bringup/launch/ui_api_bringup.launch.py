"""ui_api_bringup.launch.py — full Pi-1 (System UI/API) bringup.

Composes existing per-subsystem launch files for the System UI/API Pi.
Launches NO new node types itself -- every node here already exists and
is independently tested; this file is composition only.

Pi-1 owns no BOM hardware at all (Raspberry Pi 5, no AI HAT, just the
10.1" touchscreen -- see docs/HARDWARE_SOFTWARE_GAP_REPORT.md /
THREE_PI_ROS2_NODE_GRAPH.md) -- unlike the Pi-2/Pi-3 bringups, there is
no bonbon_hal include here at all.

bonbon_fault_manager runs HERE (Pi-1), not Pi-2/Pi-3, because its sole
consumer (bonbon_operator_api's dashboard) is co-located, and it
subscribes network-wide via normal DDS discovery (all three Pis share
ROS_DOMAIN_ID) -- no bridging needed, no reason to run three redundant
instances.

Usage:
  ros2 launch bonbon_ui_api_bringup ui_api_bringup.launch.py
  ros2 launch bonbon_ui_api_bringup ui_api_bringup.launch.py port:=8080
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def _include(pkg: str, launch_file: str, launch_arguments: dict | None = None):
    path = os.path.join(get_package_share_directory(pkg), "launch", launch_file)
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path),
        launch_arguments=(launch_arguments or {}).items(),
    )


def generate_launch_description() -> LaunchDescription:
    # ── Rank 1: operator API (dashboard/touchscreen backend) ─────────────
    operator_api = _include(
        "bonbon_operator_api",
        "operator_api.launch.py",
        {
            "host": LaunchConfiguration("host"),
            "port": LaunchConfiguration("port"),
            "ros2_enabled": LaunchConfiguration("ros2_enabled"),
        },
    )

    # ── Rank 2: fault registry aggregator -- co-located with its sole
    #    consumer, the dashboard above ────────────────────────────────────
    fault_manager = _include("bonbon_fault_manager", "fault_manager.launch.py")

    # ── Cross-Pi liveness + authority (self_id=pi1) ──────────────────────
    distributed_safety = LifecycleNode(
        package="bonbon_distributed_safety",
        executable="distributed_safety_node",
        name="distributed_safety_node",
        namespace="",
        parameters=[{"self_id": "pi1"}],
        output="screen",
    )
    authority_manager = LifecycleNode(
        package="bonbon_authority_manager",
        executable="authority_manager_node",
        name="authority_manager_node",
        namespace="",
        parameters=[{"self_id": "pi1"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "host", default_value="0.0.0.0", description="API server bind host"
            ),
            DeclareLaunchArgument("port", default_value="8080", description="API server port"),
            DeclareLaunchArgument(
                "ros2_enabled", default_value="true", description="Enable ROS2 bridge"
            ),
            operator_api,
            fault_manager,
            distributed_safety,
            authority_manager,
        ]
    )
