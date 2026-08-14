"""ai_pi_edge.launch.py — Edge AI Runtime brief Phase 10. AI Interaction
Pi (Pi-2) launch: the existing, already-tested full Pi-2 bringup
(bonbon_human_ai_bringup) PLUS the one new node this brief adds --
edge_ai_runtime_node, which owns the real TaskRouter/
SafetySeparationGuard/CacheManager/ResourceGuard/InferenceScheduler
state and publishes the 6 status topics Phase 12's dashboard reads.

Launches NO new AI/perception/actuation node types beyond that single
addition -- everything else is the existing bringup, included exactly
as human_ai_bringup.launch.py already composes it. See
docs/DUPLICATE_PIPELINE_AUDIT.md for why this brief's "AI Pi" launch
does not reimplement ASR/TTS/LLM/vision/gesture/affective bringup that
already exists and is already tested.

ALSO launches hardware_telemetry_node with pi_role=ai_interaction_pi --
this Pi has no HAL hardware either, so it only samples this Pi's own
CPU/memory/disk (see bonbon_hardware_telemetry.nodes
.hardware_telemetry_node's docstring for the pi_role gating).

ALSO launches network_monitor_node -- every Pi runs its own local
chrony offset check (see bonbon_distributed_network_monitor's own
docstring).

Usage:
  ros2 launch launch/edge_ai/ai_pi_edge.launch.py driver_mode:=real
  ros2 launch launch/edge_ai/ai_pi_edge.launch.py   # mock, dev/CI

  # Or, once installed into a package share dir:
  ros2 launch bonbon_edge_ai_runtime ai_pi_edge.launch.py
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from launch import LaunchDescription


def _include(pkg: str, launch_file: str, launch_arguments: dict | None = None):
    path = os.path.join(get_package_share_directory(pkg), "launch", launch_file)
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path),
        launch_arguments=(launch_arguments or {}).items(),
    )


def generate_launch_description() -> LaunchDescription:
    human_ai = _include(
        "bonbon_human_ai_bringup",
        "human_ai_bringup.launch.py",
        {
            "driver_mode": LaunchConfiguration("driver_mode"),
            "detector_backend": LaunchConfiguration("detector_backend"),
            "model_path": LaunchConfiguration("model_path"),
            "face_detect_backend": LaunchConfiguration("face_detect_backend"),
            "face_recognize_backend": LaunchConfiguration("face_recognize_backend"),
            "face_db_path": LaunchConfiguration("face_db_path"),
            "stt_backend": LaunchConfiguration("stt_backend"),
            "stt_model_size": LaunchConfiguration("stt_model_size"),
            "stt_model_dir": LaunchConfiguration("stt_model_dir"),
            "diarization_enabled": LaunchConfiguration("diarization_enabled"),
            "diarization_hf_token": LaunchConfiguration("diarization_hf_token"),
        },
    )

    edge_ai_runtime = Node(
        package="bonbon_edge_ai_runtime",
        executable="edge_ai_runtime_node",
        name="edge_ai_runtime_node",
        namespace="",
        parameters=[{"publish_interval_sec": LaunchConfiguration("edge_ai_publish_interval_sec")}],
        output="screen",
    )

    hardware_telemetry = Node(
        package="bonbon_hardware_telemetry",
        executable="hardware_telemetry_node",
        name="hardware_telemetry_node",
        namespace="",
        parameters=[
            {
                "pi_role": "ai_interaction_pi",
                "publish_interval_sec": LaunchConfiguration(
                    "hardware_telemetry_publish_interval_sec"
                ),
            }
        ],
        output="screen",
    )

    network_monitor = Node(
        package="bonbon_distributed_network_monitor",
        executable="network_monitor_node",
        name="network_monitor_node",
        namespace="",
        parameters=[{"pi_role": "ai_interaction_pi"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("driver_mode", default_value="mock", description="real|mock"),
            DeclareLaunchArgument("detector_backend", default_value="mock"),
            DeclareLaunchArgument("model_path", default_value=""),
            DeclareLaunchArgument("face_detect_backend", default_value="mock"),
            DeclareLaunchArgument("face_recognize_backend", default_value="mock"),
            DeclareLaunchArgument("face_db_path", default_value=""),
            DeclareLaunchArgument("stt_backend", default_value="mock"),
            DeclareLaunchArgument("stt_model_size", default_value="base"),
            DeclareLaunchArgument("stt_model_dir", default_value=""),
            DeclareLaunchArgument("diarization_enabled", default_value="false"),
            DeclareLaunchArgument("diarization_hf_token", default_value=""),
            DeclareLaunchArgument(
                "edge_ai_publish_interval_sec",
                default_value="2.0",
                description="How often edge_ai_runtime_node republishes dashboard status",
            ),
            DeclareLaunchArgument(
                "hardware_telemetry_publish_interval_sec",
                default_value="2.0",
                description="How often hardware_telemetry_node republishes dashboard status",
            ),
            human_ai,
            edge_ai_runtime,
            hardware_telemetry,
            network_monitor,
        ]
    )
