"""Launches motion_approval_gateway_node. Pi-3 only -- do not include this
launch file in any Pi-1 or Pi-2 bringup; see
config/distributed/pi_navigation_safety.yaml and
docs/DISTRIBUTED_TOPIC_SERVICE_CONTRACT.md.
"""

from launch import LaunchDescription
from launch_ros.actions import LifecycleNode


def generate_launch_description() -> LaunchDescription:
    node = LifecycleNode(
        package="bonbon_motion_approval_gateway",
        executable="motion_approval_gateway_node",
        name="motion_approval_gateway_node",
        namespace="",
        output="screen",
    )
    return LaunchDescription([node])
