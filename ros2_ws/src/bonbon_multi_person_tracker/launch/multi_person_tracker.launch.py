"""Launch file for bonbon_multi_person_tracker — person identity lifecycle LifecycleNode."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessStart
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

    # configure_event previously sat as a top-level LaunchDescription action
    # alongside tracker_node itself, with no OnProcessStart gate -- launch
    # visits both essentially immediately, so the CONFIGURE transition
    # request raced the node's actual startup (rclpy init, lifecycle
    # service creation) instead of waiting for it. Confirmed on real Pi-2
    # hardware: the transition failed ~2.9s after the process was spawned
    # -- too fast for the node to be ready, and far too fast to be the
    # unbounded-network-call timeout pattern seen elsewhere (llm/asr).
    # Every other lifecycle launch file in this repo gates its initial
    # configure_event behind OnProcessStart; this one didn't.
    on_start_configure = RegisterEventHandler(
        OnProcessStart(
            target_action=tracker_node,
            on_start=[configure_event],
        )
    )

    return LaunchDescription(
        [
            log_level_arg,
            tracker_node,
            on_start_configure,
            on_configured,
        ]
    )
