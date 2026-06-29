"""Launch file for bonbon_multi_person_tracker — person identity lifecycle LifecycleNode."""

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
        get_package_share_directory("bonbon_multi_person_tracker"),
        "config",
        "multi_person_tracker_params.yaml",
    )

    log_level_arg = DeclareLaunchArgument(
        "log_level",
        default_value="info",
        description="ROS2 logger level for multi_person_tracker_node",
    )

    tracker_node = LifecycleNode(
        package="bonbon_multi_person_tracker",
        executable="multi_person_tracker_node",
        name="multi_person_tracker_node",
        namespace="bonbon",
        parameters=[config_path],
        output="screen",
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is tracker_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is tracker_node,
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )

    on_configured = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=tracker_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[activate_event],
        )
    )

    return LaunchDescription(
        [
            log_level_arg,
            tracker_node,
            configure_event,
            on_configured,
        ]
    )
