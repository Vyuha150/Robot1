"""Launch file for the BonBon Patient Kiosk API node."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, RegisterEventHandler
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    config_file = Path(__file__).parent.parent / "config" / "kiosk_api_params.yaml"

    declare_host = DeclareLaunchArgument("host", default_value="0.0.0.0", description="API server bind host")
    declare_port = DeclareLaunchArgument("port", default_value="8090", description="API server port")
    declare_ros2_enabled = DeclareLaunchArgument(
        "ros2_enabled", default_value="true", description="Enable ROS2 bridge"
    )

    kiosk_api_node = LifecycleNode(
        package="bonbon_patient_kiosk",
        executable="kiosk_api_node",
        name="bonbon_patient_kiosk",
        namespace="",
        parameters=[
            str(config_file),
            {
                "host": LaunchConfiguration("host"),
                "port": LaunchConfiguration("port"),
                "ros2_enabled": LaunchConfiguration("ros2_enabled"),
            },
        ],
        output="screen",
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=lambda node: node is kiosk_api_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )
    activate_on_configure = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=kiosk_api_node,
            goal_state="inactive",
            entities=[
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=lambda n: n is kiosk_api_node,
                        transition_id=Transition.TRANSITION_ACTIVATE,
                    )
                )
            ],
        )
    )

    return LaunchDescription(
        [declare_host, declare_port, declare_ros2_enabled, kiosk_api_node, configure_event, activate_on_configure]
    )
