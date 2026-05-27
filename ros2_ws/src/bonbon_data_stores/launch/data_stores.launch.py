"""Launch file for the bonbon_data_stores LifecycleNode."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description() -> LaunchDescription:
    pkg_share = Path(__file__).resolve().parent.parent
    default_params = str(pkg_share / "config" / "data_store_params.yaml")

    params_arg = DeclareLaunchArgument(
        "params_file",
        default_value=default_params,
        description="Full path to the ROS2 parameter YAML file.",
    )

    data_store_node = LifecycleNode(
        package="bonbon_data_stores",
        executable="data_store_node",
        name="data_store_node",
        namespace="bonbon",
        parameters=[LaunchConfiguration("params_file")],
        output="screen",
        emulate_tty=True,
    )

    # Auto-configure → activate on launch
    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is data_store_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )

    activate_on_configured = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=data_store_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=lambda node: node is data_store_node,
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        )
    )

    return LaunchDescription(
        [
            params_arg,
            data_store_node,
            configure_event,
            activate_on_configured,
        ]
    )
