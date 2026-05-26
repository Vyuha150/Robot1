"""
launch/tts.launch.py
======================
Launch the bonbon_tts LifecycleNode and auto-transition it to Active.

Usage::

    ros2 launch bonbon_tts tts.launch.py
    ros2 launch bonbon_tts tts.launch.py model_path:=/path/to/model.onnx
    ros2 launch bonbon_tts tts.launch.py speaker_driver:=hal volume_pct:=90.0

Launch arguments
----------------
model_path       Path to Piper .onnx model (default: "").
speaker_driver   "mock" or "hal" (default: "mock").
volume_pct       Playback volume 0–100 (default: 80.0).
filler_enabled   Enable filler clips (default: "true").
health_rate_hz   Health publish rate (default: 1.0).
"""
from __future__ import annotations

import os

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    LogInfo,
    RegisterEventHandler,
)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.events.lifecycle import ChangeState
from launch_ros.event_handlers import OnStateTransition
import lifecycle_msgs.msg


def generate_launch_description() -> LaunchDescription:
    # ── Parameter file ─────────────────────────────────────────────────────
    pkg_share = os.path.join(
        os.path.dirname(__file__), "..", "config", "tts_params.yaml"
    )
    params_file = os.path.realpath(pkg_share)

    # ── Launch arguments ───────────────────────────────────────────────────
    model_path_arg = DeclareLaunchArgument(
        "model_path", default_value="",
        description="Absolute path to Piper .onnx model file",
    )
    speaker_driver_arg = DeclareLaunchArgument(
        "speaker_driver", default_value="mock",
        description="Speaker driver: 'mock' or 'hal'",
    )
    volume_arg = DeclareLaunchArgument(
        "volume_pct", default_value="80.0",
        description="Playback volume 0–100",
    )
    filler_arg = DeclareLaunchArgument(
        "filler_enabled", default_value="true",
        description="Enable filler audio clips",
    )
    health_rate_arg = DeclareLaunchArgument(
        "health_rate_hz", default_value="1.0",
        description="Health topic publish rate (Hz)",
    )

    # ── TTS lifecycle node ─────────────────────────────────────────────────
    tts_node = LifecycleNode(
        package    = "bonbon_tts",
        executable = "tts_node",
        name       = "tts_node",
        namespace  = "",
        parameters = [
            params_file,
            {
                "piper.model_path":   LaunchConfiguration("model_path"),
                "speaker.driver":     LaunchConfiguration("speaker_driver"),
                "speaker.volume_pct": LaunchConfiguration("volume_pct"),
                "filler.enabled":     LaunchConfiguration("filler_enabled"),
                "health_rate_hz":     LaunchConfiguration("health_rate_hz"),
            },
        ],
        output = "screen",
    )

    # ── Auto-configure transition ──────────────────────────────────────────
    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=tts_node,
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        )
    )

    # ── Auto-activate after configure ─────────────────────────────────────
    activate_after_configure = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node = tts_node,
            goal_state            = "inactive",
            entities              = [
                LogInfo(msg="TTS node configured → activating"),
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=tts_node,
                        transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
                    )
                ),
            ],
        )
    )

    return LaunchDescription([
        model_path_arg,
        speaker_driver_arg,
        volume_arg,
        filler_arg,
        health_rate_arg,
        tts_node,
        configure_event,
        activate_after_configure,
    ])
