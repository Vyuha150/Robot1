"""Launch file for bonbon_behavior_engine — BehaviorEngineNode LifecycleNode."""

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
        get_package_share_directory("bonbon_behavior_engine"),
        "config",
        "behavior_engine.yaml",
    )

    log_level_arg = DeclareLaunchArgument(
        "log_level",
        default_value="info",
        description="Logger level for behavior_engine_node",
    )

    mode_arg = DeclareLaunchArgument(
        "operating_mode",
        default_value="normal",
        description="Operating mode: normal|child_safe|elderly|demo|emergency",
    )

    behavior_node = LifecycleNode(
        package="bonbon_behavior_engine",
        executable="behavior_engine_node",
        name="behavior_engine_node",
        namespace="bonbon",
        parameters=[
            config_path,
            {"operating_mode": LaunchConfiguration("operating_mode")},
        ],
        output="screen",
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is behavior_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is behavior_node,
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )

    on_configured = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=behavior_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[activate_event],
        )
    )

    return LaunchDescription([
        log_level_arg,
        mode_arg,
        behavior_node,
        configure_event,
        on_configured,
    ])
