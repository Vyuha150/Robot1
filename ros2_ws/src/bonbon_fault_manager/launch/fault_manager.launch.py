"""Launches fault_manager_node.

Runs on Pi-1 by default (co-located with the dashboard API it feeds),
but subscribes network-wide -- all three Pis share ROS_DOMAIN_ID per
config/distributed/robot_network.yaml, so HalFault/SafetyState from
Pi-2/Pi-3 are visible here via normal DDS discovery, no bridging needed.

Usage: ros2 launch bonbon_fault_manager fault_manager.launch.py
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def generate_launch_description() -> LaunchDescription:
    rate_arg = DeclareLaunchArgument(
        "republish_rate_hz",
        default_value="1.0",
        description="Periodic full-registry republish rate (Hz), for late dashboard joiners",
    )
    node = LifecycleNode(
        package="bonbon_fault_manager",
        executable="fault_manager_node",
        name="fault_manager_node",
        namespace="",
        parameters=[{"republish_rate_hz": LaunchConfiguration("republish_rate_hz")}],
        output="screen",
    )
    return LaunchDescription([rate_arg, node])
