"""human_ai_bringup.launch.py — full Pi-2 (Human AI) bringup.

Composes existing per-subsystem launch files in the boot order specified
by config/distributed/pi_human_ai.yaml. Launches NO new node types itself
-- every node here already exists and is independently tested; this file
is composition + correct Pi-2-only HAL scoping only.

Explicitly launches ONLY camera/mic/speaker HAL devices (lidar/servo/
motor/estop/battery/imu are Pi-3 hardware) -- this is the concrete fix for
docs/DISTRIBUTED_DEPLOYMENT_BLOCKERS.md Blocker 2 ("no per-Pi launch
files... a Pi could accidentally launch the full monolithic stack").

Usage:
  ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py driver_mode:=real
  ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py   # mock, dev/CI
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def _include(pkg: str, launch_file: str, launch_arguments: dict | None = None):
    path = os.path.join(get_package_share_directory(pkg), "launch", launch_file)
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(path),
        launch_arguments=(launch_arguments or {}).items(),
    )


def generate_launch_description() -> LaunchDescription:
    driver_mode = LaunchConfiguration("driver_mode")
    overrides = os.path.join(
        get_package_share_directory("bonbon_human_ai_bringup"),
        "config",
        "pi2_hal_overrides.yaml",
    )

    # ── Rank 1-2: sensors first (camera + mic + speaker ONLY -- see module
    #    docstring for why lidar/servo/motor/estop/battery/imu are excluded) ──
    hal = _include(
        "bonbon_hal",
        "hal.launch.py",
        {
            "driver_mode": driver_mode,
            "override_params_file": overrides,
            "launch_lidar": "false",
            "launch_imu": "false",
            "launch_servo": "false",
            "launch_motor": "false",
            "launch_battery": "false",
            "launch_estop": "false",
            "launch_camera": "true",
            "launch_mic": "true",
            "launch_speaker": "true",
        },
    )

    # ── Rank 3: ASR (requires mic) ────────────────────────────────────────────
    asr = _include("bonbon_speech", "speech.launch.py")

    # ── Rank 4: face recognition (runs inline in vision_node, requires camera) ─
    vision = _include("bonbon_vision", "vision.launch.py")

    # ── Rank 5: perception fusion group (tracker, object, gesture, affective,
    #    human_state_fusion, speaker_intelligence) ────────────────────────────
    tracker = _include("bonbon_multi_person_tracker", "multi_person_tracker.launch.py")
    objects = _include("bonbon_object_intelligence", "object_intelligence.launch.py")
    gesture = _include("bonbon_gesture", "gesture.launch.py")
    affective = _include("bonbon_affective_ai", "affective_ai.launch.py")
    human_state = _include("bonbon_human_state_fusion", "human_state_fusion.launch.py")
    speaker_intel = _include("bonbon_speaker_intelligence", "speaker_intelligence.launch.py")

    # ── Rank 6: local LLM -- slowest to warm up, started after sensors ───────
    llm = TimerAction(
        period=3.0,
        actions=[_include("bonbon_llm", "llm.launch.py")],
    )

    # ── Rank 7: TTS ────────────────────────────────────────────────────────────
    tts = _include("bonbon_tts", "tts.launch.py")

    # ── Cross-Pi liveness + authority (self_id=pi2, see bonbon_distributed_safety
    #    / bonbon_authority_manager, Phase 3 of the three-Pi architecture) ──────
    distributed_safety = LifecycleNode(
        package="bonbon_distributed_safety",
        executable="distributed_safety_node",
        name="distributed_safety_node",
        namespace="",
        parameters=[{"self_id": "pi2"}],
        output="screen",
    )
    authority_manager = LifecycleNode(
        package="bonbon_authority_manager",
        executable="authority_manager_node",
        name="authority_manager_node",
        namespace="",
        parameters=[{"self_id": "pi2"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "driver_mode", default_value="mock", description="real|mock — HAL driver mode"
            ),
            hal,
            distributed_safety,
            authority_manager,
            asr,
            vision,
            tracker,
            objects,
            gesture,
            affective,
            human_state,
            speaker_intel,
            llm,
            tts,
        ]
    )
