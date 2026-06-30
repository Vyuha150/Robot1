"""Launch file for bonbon_data_feedback — failure-case logging, hard-negative
collection, privacy-safe retention LifecycleNode."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description() -> LaunchDescription:
    config_path = os.path.join(
        get_package_share_directory("bonbon_data_feedback"),
        "config",
        "data_feedback_params.yaml",
    )

    log_level_arg = DeclareLaunchArgument(
        "log_level", default_value="info", description="ROS2 logger level"
    )
    debug_mode_arg = DeclareLaunchArgument(
        "debug_mode_enabled",
        default_value="false",
        description="Allow raw face/audio snapshot storage. NEVER true in production.",
    )

    feedback_node = LifecycleNode(
        package="bonbon_data_feedback",
        executable="data_feedback_node",
        name="data_feedback_node",
        namespace="bonbon",
        parameters=[config_path, {"debug_mode_enabled": LaunchConfiguration("debug_mode_enabled")}],
        output="screen",
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is feedback_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )
    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is feedback_node,
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )
    on_configured = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=feedback_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[activate_event],
        )
    )

    return LaunchDescription(
        [
            log_level_arg,
            debug_mode_arg,
            feedback_node,
            configure_event,
            on_configured,
        ]
    )
