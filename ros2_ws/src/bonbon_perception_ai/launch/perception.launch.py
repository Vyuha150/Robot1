"""
bonbon_perception_ai — ROS2 launch file.

Launches PerceptionAINode as a managed lifecycle node and immediately
configures + activates it.

Usage
-----
    # Defaults (rule-based intent, in-memory SQLite)
    ros2 launch bonbon_perception_ai perception.launch.py

    # With LangChain intent backend
    ros2 launch bonbon_perception_ai perception.launch.py \
        intent_backend:=langchain \
        langchain_api_key:=sk-...

    # With persistent SQLite memory and diarization privacy
    ros2 launch bonbon_perception_ai perception.launch.py \
        memory_db_path:=/var/bonbon/memory.db \
        privacy_anonymize_persons:=true
"""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition  # type: ignore


def generate_launch_description() -> LaunchDescription:
    # ── Launch arguments ──────────────────────────────────────────────────────
    args = [
        DeclareLaunchArgument("node_name", default_value="perception_ai_node"),
        DeclareLaunchArgument("log_level", default_value="info"),
        # Fusion
        DeclareLaunchArgument("objects_stale_sec", default_value="2.0"),
        DeclareLaunchArgument("persons_stale_sec", default_value="2.0"),
        DeclareLaunchArgument("speech_stale_sec", default_value="8.0"),
        # Scene
        DeclareLaunchArgument("near_person_threshold_m", default_value="2.0"),
        DeclareLaunchArgument("interaction_proximity_m", default_value="1.5"),
        DeclareLaunchArgument("crowded_threshold", default_value="3"),
        # Intent
        DeclareLaunchArgument("intent_backend", default_value="rule_based"),
        DeclareLaunchArgument("langchain_model", default_value="gpt-3.5-turbo"),
        DeclareLaunchArgument("langchain_api_key", default_value=""),
        DeclareLaunchArgument("intent_confidence_threshold", default_value="0.55"),
        DeclareLaunchArgument("ambiguity_policy", default_value="clarify"),
        # Risk
        DeclareLaunchArgument("critical_proximity_m", default_value="0.40"),
        DeclareLaunchArgument("caution_proximity_m", default_value="1.20"),
        # Memory
        DeclareLaunchArgument("memory_db_path", default_value=""),
        DeclareLaunchArgument("memory_episode_ttl_days", default_value="7.0"),
        DeclareLaunchArgument("memory_privacy_anonymize_persons", default_value="false"),
        DeclareLaunchArgument("memory_privacy_store_faces", default_value="false"),
        # Privacy
        DeclareLaunchArgument("privacy_anonymize_persons", default_value="false"),
        DeclareLaunchArgument("privacy_store_faces", default_value="false"),
        DeclareLaunchArgument("privacy_suppress_speaker", default_value="false"),
        # Node
        DeclareLaunchArgument("scene_publish_rate_hz", default_value="10.0"),
        DeclareLaunchArgument("health_rate_hz", default_value="1.0"),
        DeclareLaunchArgument("allow_degraded_startup", default_value="false"),
    ]

    node = LifecycleNode(
        package="bonbon_perception_ai",
        executable="perception_ai_node",
        name=LaunchConfiguration("node_name"),
        output="screen",
        respawn=True,
        respawn_delay=2.0,
        parameters=[
            {
                "fusion.objects_stale_sec": LaunchConfiguration("objects_stale_sec"),
                "fusion.persons_stale_sec": LaunchConfiguration("persons_stale_sec"),
                "fusion.speech_stale_sec": LaunchConfiguration("speech_stale_sec"),
                "scene.near_person_threshold_m": LaunchConfiguration("near_person_threshold_m"),
                "scene.interaction_proximity_m": LaunchConfiguration("interaction_proximity_m"),
                "scene.crowded_threshold": LaunchConfiguration("crowded_threshold"),
                "intent.backend": LaunchConfiguration("intent_backend"),
                "intent.langchain_model": LaunchConfiguration("langchain_model"),
                "intent.langchain_api_key": LaunchConfiguration("langchain_api_key"),
                "intent.intent_confidence_threshold": LaunchConfiguration(
                    "intent_confidence_threshold"
                ),
                "intent.ambiguity_policy": LaunchConfiguration("ambiguity_policy"),
                "risk.critical_proximity_m": LaunchConfiguration("critical_proximity_m"),
                "risk.caution_proximity_m": LaunchConfiguration("caution_proximity_m"),
                "memory.db_path": LaunchConfiguration("memory_db_path"),
                "memory.episode_ttl_days": LaunchConfiguration("memory_episode_ttl_days"),
                "memory.privacy_anonymize_persons": LaunchConfiguration(
                    "memory_privacy_anonymize_persons"
                ),
                "memory.privacy_store_faces": LaunchConfiguration("memory_privacy_store_faces"),
                "privacy.anonymize_persons": LaunchConfiguration("privacy_anonymize_persons"),
                "privacy.store_faces": LaunchConfiguration("privacy_store_faces"),
                "privacy.suppress_speaker_id": LaunchConfiguration("privacy_suppress_speaker"),
                "scene_publish_rate_hz": LaunchConfiguration("scene_publish_rate_hz"),
                "health_rate_hz": LaunchConfiguration("health_rate_hz"),
                "allow_degraded_startup": LaunchConfiguration("allow_degraded_startup"),
            }
        ],
    )

    configure = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=node,
            transition_id=Transition.TRANSITION_CONFIGURE,
        )
    )
    activate = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=node,
            transition_id=Transition.TRANSITION_ACTIVATE,
        )
    )

    return LaunchDescription(args + [node, configure, activate])
