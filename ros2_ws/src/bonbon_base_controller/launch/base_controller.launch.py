"""Launches base_controller_node. Pi-3 only -- requires bonbon_hal's
motor_node (Cytron MDDS30) and bonbon_safety's safety_gate_node (the sole
publisher of /cmd_vel) to already be running."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def generate_launch_description() -> LaunchDescription:
    wheel_base_arg = DeclareLaunchArgument(
        "wheel_base_m",
        default_value="0.40",
        description="Distance between wheel contact points (metres) — VERIFY against physical robot",
    )
    max_speed_arg = DeclareLaunchArgument(
        "max_wheel_speed_mps", default_value="1.0", description="Per-wheel speed cap, metres/second"
    )
    node = LifecycleNode(
        package="bonbon_base_controller",
        executable="base_controller_node",
        name="base_controller_node",
        namespace="",
        parameters=[
            {
                "wheel_base_m": LaunchConfiguration("wheel_base_m"),
                "max_wheel_speed_mps": LaunchConfiguration("max_wheel_speed_mps"),
            }
        ],
        output="screen",
    )
    return LaunchDescription([wheel_base_arg, max_speed_arg, node])
