"""
bonbon_vision — Vision Module Launch File
==========================================
Launches vision_node as a ROS2 LifecycleNode with configurable backends.

Usage examples
--------------
# Default (mock backend, no real camera):
  ros2 launch bonbon_vision vision.launch.py

# YOLOv8 with real camera:
  ros2 launch bonbon_vision vision.launch.py \\
      detector_backend:=yolo \\
      model_path:=/opt/models/yolov8n.pt \\
      publish_annotated:=true

# Privacy mode on:
  ros2 launch bonbon_vision vision.launch.py \\
      privacy_enabled:=true \\
      pixelate_faces:=true

# Face recognition with InsightFace:
  ros2 launch bonbon_vision vision.launch.py \\
      face_detect_backend:=insightface \\
      face_recognize_backend:=insightface \\
      face_db_path:=/opt/faces/db

Arguments
---------
All launch arguments have safe defaults that run without real hardware.
Model paths default to empty strings — vision_node enters degraded mode
gracefully when backend='yolo' but model_path is empty.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    LogInfo,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessStart
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from launch_ros.substitutions import FindPackageShare
from lifecycle_msgs.msg import Transition


def generate_launch_description() -> LaunchDescription:

    # ── Launch arguments ──────────────────────────────────────────────────────

    args = [
        # Frame rate
        DeclareLaunchArgument(
            "detection_rate_hz",
            default_value="10.0",
            description="Target detection frames per second",
        ),
        # Detector
        DeclareLaunchArgument(
            "detector_backend",
            default_value="mock",
            description="Object detector backend: mock | yolo",
        ),
        DeclareLaunchArgument(
            "model_path", default_value="", description="Absolute path to YOLO .pt model file"
        ),
        DeclareLaunchArgument(
            "detector_confidence", default_value="0.45", description="YOLO confidence threshold"
        ),
        DeclareLaunchArgument(
            "detector_device",
            default_value="",
            description="Inference device: '' (auto) | cpu | cuda:0",
        ),
        DeclareLaunchArgument(
            "detector_half",
            default_value="false",
            description="Enable FP16 half-precision inference",
        ),
        # Face pipeline
        DeclareLaunchArgument(
            "face_detect_backend",
            default_value="mock",
            description="Face detector: mock | opencv_dnn | insightface",
        ),
        DeclareLaunchArgument(
            "face_recognize_backend",
            default_value="mock",
            description="Face recognizer: mock | insightface | deepface",
        ),
        DeclareLaunchArgument(
            "face_db_path", default_value="", description="Path to face identity database"
        ),
        DeclareLaunchArgument(
            "face_threshold",
            default_value="0.40",
            description="Cosine distance threshold for face recognition",
        ),
        # Privacy
        DeclareLaunchArgument(
            "privacy_enabled",
            default_value="false",
            description="Enable face anonymisation on published images",
        ),
        DeclareLaunchArgument(
            "pixelate_faces",
            default_value="false",
            description="Use pixelation instead of Gaussian blur",
        ),
        DeclareLaunchArgument(
            "suppress_identity",
            default_value="true",
            description="Omit face_id from published messages",
        ),
        # Publishing
        DeclareLaunchArgument(
            "publish_annotated",
            default_value="false",
            description="Publish annotated image (debug; adds latency)",
        ),
        # Degraded mode
        DeclareLaunchArgument(
            "allow_degraded",
            default_value="true",
            description="Allow startup in degraded mode if model fails",
        ),
        # Auto-activate (skip manual lifecycle transitions in development)
        DeclareLaunchArgument(
            "auto_activate",
            default_value="true",
            description="Automatically configure and activate the node",
        ),
    ]

    # ── Default parameter file ────────────────────────────────────────────────

    default_params = PathJoinSubstitution(
        [FindPackageShare("bonbon_vision"), "config", "vision_params.yaml"]
    )

    # ── vision_node (LifecycleNode) ───────────────────────────────────────────

    vision_node = LifecycleNode(
        package="bonbon_vision",
        executable="vision_node",
        name="vision_node",
        namespace="/bonbon/vision",
        output="screen",
        emulate_tty=True,
        parameters=[
            default_params,
            {
                # Override defaults with launch-argument values
                "detection_rate_hz": LaunchConfiguration("detection_rate_hz"),
                "publish_annotated_image": LaunchConfiguration("publish_annotated"),
                "allow_degraded_startup": LaunchConfiguration("allow_degraded"),
                "detector.backend": LaunchConfiguration("detector_backend"),
                "detector.model_path": LaunchConfiguration("model_path"),
                "detector.confidence_threshold": LaunchConfiguration("detector_confidence"),
                "detector.device": LaunchConfiguration("detector_device"),
                "detector.half_precision": LaunchConfiguration("detector_half"),
                "face.detect_backend": LaunchConfiguration("face_detect_backend"),
                "face.recognize_backend": LaunchConfiguration("face_recognize_backend"),
                "face.db_path": LaunchConfiguration("face_db_path"),
                "face.recognition_threshold": LaunchConfiguration("face_threshold"),
                "privacy.enabled": LaunchConfiguration("privacy_enabled"),
                "privacy.pixelate_faces": LaunchConfiguration("pixelate_faces"),
                "privacy.suppress_identity": LaunchConfiguration("suppress_identity"),
            },
        ],
        respawn=True,
        respawn_delay=2.0,
    )

    # ── Auto lifecycle transitions ────────────────────────────────────────────
    # configure → activate when auto_activate=true

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(vision_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        ),
        condition=IfCondition(LaunchConfiguration("auto_activate")),
    )

    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(vision_node),
            transition_id=Transition.TRANSITION_ACTIVATE,
        ),
        condition=IfCondition(LaunchConfiguration("auto_activate")),
    )

    # Trigger configure on node start
    on_start_configure = RegisterEventHandler(
        OnProcessStart(
            target_action=vision_node,
            on_start=[configure_event],
        ),
        condition=IfCondition(LaunchConfiguration("auto_activate")),
    )

    # Trigger activate once node reaches "inactive" state
    on_inactive_activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=vision_node,
            start_state="configuring",
            goal_state="inactive",
            entities=[activate_event],
        ),
        condition=IfCondition(LaunchConfiguration("auto_activate")),
    )

    # Log active
    on_active_log = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=vision_node,
            start_state="activating",
            goal_state="active",
            entities=[
                LogInfo(msg="[bonbon_vision] vision_node is ACTIVE — detection running"),
            ],
        ),
    )

    return LaunchDescription(
        args
        + [
            vision_node,
            on_start_configure,
            on_inactive_activate,
            on_active_log,
        ]
    )
