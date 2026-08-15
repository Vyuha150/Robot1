"""
perception.launch.py
=====================
Launches the BonBon perception subsystem:

  1. detection_node  — person detection + multi-object tracking (CLASS-C)
  2. face_node       — face recognition / identity (CLASS-D)

Usage
-----
  # Simulation (mock detectors, no hardware)
  ros2 launch bonbon_perception perception.launch.py

  # HOG detector (OpenCV, CPU only)
  ros2 launch bonbon_perception perception.launch.py detector_mode:=hog

  # YOLOv8 (requires ultralytics + model file)
  ros2 launch bonbon_perception perception.launch.py \\
      detector_mode:=yolo model_path:=/opt/bonbon/models/yolov8n.pt

  # Face recognition with DeepFace
  ros2 launch bonbon_perception perception.launch.py \\
      face_mode:=deepface face_db_path:=/var/lib/bonbon/face_db.sqlite

  # Disable face node (saves CPU on resource-constrained deployments)
  ros2 launch bonbon_perception perception.launch.py launch_face:=false

  # With safety subsystem already running (typical deployment)
  ros2 launch bonbon_safety safety.launch.py simulation:=true &
  ros2 launch bonbon_hal hal.launch.py &
  ros2 launch bonbon_perception perception.launch.py
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    LogInfo,
    OpaqueFunction,
)
from launch_ros.actions import LifecycleNode


def _perception_nodes(context, *args, **kwargs) -> list:
    pkg_share = get_package_share_directory("bonbon_perception")
    base_params = os.path.join(pkg_share, "config", "perception_params.yaml")

    detector_mode = context.launch_configurations.get("detector_mode", "mock")
    model_path = context.launch_configurations.get("model_path", "yolov8n.pt")
    face_mode = context.launch_configurations.get("face_mode", "mock")
    face_db_path = context.launch_configurations.get(
        "face_db_path", "/var/lib/bonbon/face_db.sqlite"
    )
    conf_threshold = float(context.launch_configurations.get("confidence_threshold", "0.5"))
    override_file = context.launch_configurations.get("override_params_file", "")

    detection_params: list = [
        base_params,
        {
            "detection_node": {
                "ros__parameters": {
                    "detector_mode": detector_mode,
                    "model_path": model_path,
                    "confidence_threshold": conf_threshold,
                }
            }
        },
    ]
    if override_file:
        detection_params.append(override_file)

    face_params: list = [
        base_params,
        {
            "face_node": {
                "ros__parameters": {
                    "face_mode": face_mode,
                    "face_db_path": face_db_path,
                }
            }
        },
    ]
    if override_file:
        face_params.append(override_file)

    launch_face = context.launch_configurations.get("launch_face", "true").lower() == "true"

    nodes = [
        # ── Detection + Tracking ─────────────────────────────────────────────
        LifecycleNode(
            package="bonbon_perception",
            executable="detection_node",
            name="detection_node",
            namespace="/bonbon",
            parameters=detection_params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
        ),
    ]

    if launch_face:
        nodes.append(
            LifecycleNode(
                package="bonbon_perception",
                executable="face_node",
                name="face_node",
                namespace="/bonbon",
                parameters=face_params,
                output="screen",
                emulate_tty=True,
                respawn=True,
                respawn_delay=3.0,
            )
        )

    return nodes


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            # ── Launch arguments ─────────────────────────────────────────────────
            DeclareLaunchArgument(
                "detector_mode",
                default_value="mock",
                description="Person detector backend: mock | hog | yolo",
            ),
            DeclareLaunchArgument(
                "model_path",
                default_value="yolov8n.pt",
                description="Path to YOLO model weights (.pt); used when detector_mode=yolo",
            ),
            DeclareLaunchArgument(
                "face_mode",
                default_value="mock",
                description="Face recognition backend: mock | opencv_lbp | deepface | insightface",
            ),
            DeclareLaunchArgument(
                "face_db_path",
                default_value="/var/lib/bonbon/face_db.sqlite",
                description="Path to SQLite face embedding database",
            ),
            DeclareLaunchArgument(
                "confidence_threshold",
                default_value="0.5",
                description="Minimum detection confidence (0.0–1.0)",
            ),
            DeclareLaunchArgument(
                "launch_face",
                default_value="true",
                description="Set false to skip face_node (saves CPU)",
            ),
            DeclareLaunchArgument(
                "override_params_file",
                default_value="",
                description="Optional site-specific parameter override YAML",
            ),
            DeclareLaunchArgument(
                "log_level",
                default_value="info",
                description="ROS2 log level: debug|info|warn|error|fatal",
            ),
            LogInfo(msg="[BonBon Perception] Launching perception subsystem…"),
            OpaqueFunction(function=_perception_nodes),
        ]
    )
