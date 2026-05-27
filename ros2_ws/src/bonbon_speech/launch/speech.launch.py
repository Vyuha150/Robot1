"""
bonbon_speech launch file
==========================
Launches the SpeechNode as a managed LifecycleNode and automatically
transitions it from unconfigured → inactive → active.

Usage
-----
# Default (mock backends, no model paths needed):
ros2 launch bonbon_speech speech.launch.py

# With Whisper STT + Silero VAD:
ros2 launch bonbon_speech speech.launch.py \
    stt_backend:=whisper stt_model_size:=base \
    vad_backend:=silero

# With wake word enabled:
ros2 launch bonbon_speech speech.launch.py \
    wake_word_enabled:=true wake_word_backend:=openwakeword \
    wake_word_model_path:=/models/hey_bonbon.tflite

# Custom params file:
ros2 launch bonbon_speech speech.launch.py \
    params_file:=/workspace/config/speech_prod.yaml
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    LogInfo,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessStart
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


def generate_launch_description():
    pkg_share = get_package_share_directory("bonbon_speech")
    default_params = os.path.join(pkg_share, "config", "speech_params.yaml")

    # ── Launch arguments ──────────────────────────────────────────────────────
    args = [
        DeclareLaunchArgument(
            "params_file",
            default_value=default_params,
            description="Path to speech node parameters YAML",
        ),
        DeclareLaunchArgument(
            "node_name",
            default_value="speech_node",
            description="ROS2 node name",
        ),
        DeclareLaunchArgument(
            "namespace",
            default_value="",
            description="ROS2 namespace",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="info",
            description="Logging level (debug|info|warn|error)",
        ),
        # VAD
        DeclareLaunchArgument(
            "vad_backend",
            default_value="silero",
            description="VAD backend: silero | mock",
        ),
        DeclareLaunchArgument(
            "vad_model_path",
            default_value="",
            description="Local path to Silero VAD model (empty = torch.hub download)",
        ),
        # STT
        DeclareLaunchArgument(
            "stt_backend",
            default_value="mock",
            description="STT backend: whisper | faster_whisper | mock",
        ),
        DeclareLaunchArgument(
            "stt_model_size",
            default_value="base",
            description="Whisper model size: tiny|base|small|medium|large",
        ),
        DeclareLaunchArgument(
            "stt_model_dir",
            default_value="",
            description="Absolute path to STT model cache directory",
        ),
        DeclareLaunchArgument(
            "stt_language",
            default_value="",
            description="Language code (empty = auto-detect)",
        ),
        # Diarization
        DeclareLaunchArgument(
            "diarization_enabled",
            default_value="false",
            description="Enable speaker diarization",
        ),
        DeclareLaunchArgument(
            "diarization_hf_token",
            default_value="",
            description="HuggingFace token for pyannote (set via secret or env)",
        ),
        # Wake word
        DeclareLaunchArgument(
            "wake_word_enabled",
            default_value="false",
            description="Enable wake-word detection",
        ),
        DeclareLaunchArgument(
            "wake_word_backend",
            default_value="mock",
            description="Wake-word backend: openwakeword | porcupine | mock",
        ),
        DeclareLaunchArgument(
            "wake_word_model_path",
            default_value="",
            description="Path to custom wake-word model file",
        ),
        # Node options
        DeclareLaunchArgument(
            "allow_degraded",
            default_value="true",
            description="Continue in degraded mode if a component fails to load",
        ),
        DeclareLaunchArgument(
            "autostart",
            default_value="true",
            description="Automatically configure and activate the node",
        ),
    ]

    # ── Node ─────────────────────────────────────────────────────────────────
    speech_node = LifecycleNode(
        package="bonbon_speech",
        executable="speech_node",
        name=LaunchConfiguration("node_name"),
        namespace=LaunchConfiguration("namespace"),
        output="screen",
        emulate_tty=True,
        parameters=[
            LaunchConfiguration("params_file"),
            {
                "vad_backend": LaunchConfiguration("vad_backend"),
                "vad_model_path": LaunchConfiguration("vad_model_path"),
                "stt_backend": LaunchConfiguration("stt_backend"),
                "stt_model_size": LaunchConfiguration("stt_model_size"),
                "stt_model_dir": LaunchConfiguration("stt_model_dir"),
                "stt_language": LaunchConfiguration("stt_language"),
                "diarization_enabled": LaunchConfiguration("diarization_enabled"),
                "diarization_hf_token": LaunchConfiguration("diarization_hf_token"),
                "wake_word_enabled": LaunchConfiguration("wake_word_enabled"),
                "wake_word_backend": LaunchConfiguration("wake_word_backend"),
                "wake_word_model_path": LaunchConfiguration("wake_word_model_path"),
                "allow_degraded": LaunchConfiguration("allow_degraded"),
            },
        ],
        arguments=["--ros-args", "--log-level", LaunchConfiguration("log_level")],
        respawn=True,
        respawn_delay=2.0,
    )

    # ── Auto configure → activate ────────────────────────────────────────────
    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=speech_node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )
    activate_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=speech_node,
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )

    # Trigger configure on node start
    on_start_configure = RegisterEventHandler(
        OnProcessStart(
            target_action=speech_node,
            on_start=[
                LogInfo(msg="SpeechNode started — sending configure transition"),
                configure_event,
            ],
        ),
        condition=IfCondition(LaunchConfiguration("autostart")),
    )

    # Trigger activate after configure completes
    on_configured_activate = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=speech_node,
            goal_state="inactive",
            entities=[
                LogInfo(msg="SpeechNode inactive — sending activate transition"),
                activate_event,
            ],
        ),
        condition=IfCondition(LaunchConfiguration("autostart")),
    )

    return LaunchDescription(
        args
        + [
            speech_node,
            on_start_configure,
            on_configured_activate,
        ]
    )
