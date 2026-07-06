"""human_ai_bringup.launch.py — full Pi-2 (Human AI) bringup.

Composes existing per-subsystem launch files in the boot order specified
by config/distributed/pi_human_ai.yaml. Launches NO new node types itself
-- every node here already exists and is independently tested; this file
is composition + correct Pi-2-only HAL scoping only.

Explicitly launches ONLY camera/mic/speaker HAL devices (lidar/servo/
stepper/motor/estop/battery/imu are Pi-3 hardware) -- this is the concrete fix for
docs/DISTRIBUTED_DEPLOYMENT_BLOCKERS.md Blocker 2 ("no per-Pi launch
files... a Pi could accidentally launch the full monolithic stack").

Usage:
  ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py driver_mode:=real
  ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py   # mock, dev/CI

  # Real AI backends (previously unreachable through this bringup -- it used
  # to call vision.launch.py/speech.launch.py with zero arguments, so their
  # own real-backend options existed but had no way to be turned on here):
  ros2 launch bonbon_human_ai_bringup human_ai_bringup.launch.py \\
      driver_mode:=real \\
      detector_backend:=yolo model_path:=/models/yolov8n.pt \\
      face_detect_backend:=insightface face_recognize_backend:=insightface \\
      stt_backend:=faster_whisper stt_model_size:=base

All AI-backend args below default to the same "mock" values
vision.launch.py/speech.launch.py already default to -- this bringup adds a
pass-through, it does not change what happens if you don't set anything.
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
    #    docstring for why lidar/servo/stepper/motor/estop/battery/imu are
    #    excluded) ──────────────────────────────────────────────────────────
    hal = _include(
        "bonbon_hal",
        "hal.launch.py",
        {
            "driver_mode": driver_mode,
            "override_params_file": overrides,
            "launch_lidar": "false",
            "launch_imu": "false",
            "launch_servo": "false",
            "launch_stepper": "false",
            "launch_motor": "false",
            "launch_battery": "false",
            "launch_estop": "false",
            "launch_camera": "true",
            "launch_mic": "true",
            "launch_speaker": "true",
        },
    )

    # ── Rank 3: ASR (requires mic) ────────────────────────────────────────────
    asr = _include(
        "bonbon_speech",
        "speech.launch.py",
        {
            "stt_backend": LaunchConfiguration("stt_backend"),
            "stt_model_size": LaunchConfiguration("stt_model_size"),
            "stt_model_dir": LaunchConfiguration("stt_model_dir"),
            "diarization_enabled": LaunchConfiguration("diarization_enabled"),
            "diarization_hf_token": LaunchConfiguration("diarization_hf_token"),
        },
    )

    # ── Rank 4: face recognition (runs inline in vision_node, requires camera) ─
    vision = _include(
        "bonbon_vision",
        "vision.launch.py",
        {
            "detector_backend": LaunchConfiguration("detector_backend"),
            "model_path": LaunchConfiguration("model_path"),
            "face_detect_backend": LaunchConfiguration("face_detect_backend"),
            "face_recognize_backend": LaunchConfiguration("face_recognize_backend"),
            "face_db_path": LaunchConfiguration("face_db_path"),
        },
    )

    # ── Rank 5: perception fusion group (tracker, object, gesture, affective,
    #    human_state_fusion, speaker_intelligence) ────────────────────────────
    tracker = _include("bonbon_multi_person_tracker", "multi_person_tracker.launch.py")
    objects = _include("bonbon_object_intelligence", "object_intelligence.launch.py")
    gesture = _include("bonbon_gesture", "gesture.launch.py")
    affective = _include("bonbon_affective_ai", "affective_ai.launch.py")
    human_state = _include("bonbon_human_state_fusion", "human_state_fusion.launch.py")
    speaker_intel = _include("bonbon_speaker_intelligence", "speaker_intelligence.launch.py")

    # ── Rank 6: local LLM -- slowest to warm up, started after sensors ───────
    # Pi-2 guard enabled here: llm.launch.py's pi2_guard_* args existed and
    # were read by LLMConfig.from_ros_params() but were never actually
    # reachable from any launch file (same class of bug as the missing
    # vision/speech backend pass-through above) -- this is precisely the
    # resource-constrained Pi-2 deployment the guard exists to protect, so
    # it is turned on here rather than left permanently unreachable.
    llm = TimerAction(
        period=3.0,
        actions=[
            _include(
                "bonbon_llm",
                "llm.launch.py",
                {
                    "ollama_model": "qwen2.5:0.5b",
                    "pi2_guard_enabled": "true",
                    "pi2_guard_max_concurrent_requests": "1",
                    "pi2_guard_max_output_tokens": "64",
                    "pi2_guard_initial_timeout_sec": "1.0",
                    "pi2_guard_cpu_disable_threshold_percent": "80.0",
                    "pi2_guard_temp_disable_threshold_c": "75.0",
                },
            )
        ],
    )

    # ── Rank 7: behavior proposal generation (fuses human_state_fusion +
    #    LLM output into BehaviorProposal messages). Pi-2 may only PROPOSE --
    #    Pi-3's safety_gate_node/motion_approval_gateway is the sole authority
    #    that can turn a proposal into actual motion. Previously missing from
    #    this bringup (only wired into the monolithic bonbon_bringup), which
    #    meant Pi-2's distributed deployment never actually sent behavior
    #    proposals to Pi-3 -- found and fixed during Pi-2 deployment prep.
    behavior_engine = TimerAction(
        period=3.5,
        actions=[_include("bonbon_behavior_engine", "behavior_engine.launch.py")],
    )

    # ── Rank 8: TTS ────────────────────────────────────────────────────────────
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
            # AI-backend pass-through args -- same defaults vision.launch.py/
            # speech.launch.py already declare on their own; this bringup
            # previously gave no way to reach them at all (see module
            # docstring). deepface intentionally not exposed here: it and
            # insightface are alternative, not complementary, face backends
            # (bonbon_vision skips deepface recognition entirely whenever
            # insightface is handling detection -- see face_pipeline.py) --
            # exposing both would invite running two overlapping face stacks
            # instead of picking one, which is the redundancy this deployment
            # must avoid.
            DeclareLaunchArgument(
                "detector_backend", default_value="mock", description="mock | yolo"
            ),
            DeclareLaunchArgument(
                "model_path", default_value="", description="Absolute path to YOLO .pt file"
            ),
            DeclareLaunchArgument(
                "face_detect_backend",
                default_value="mock",
                description="mock | opencv_dnn | insightface",
            ),
            DeclareLaunchArgument(
                "face_recognize_backend", default_value="mock", description="mock | insightface"
            ),
            DeclareLaunchArgument(
                "face_db_path", default_value="", description="Path to face identity database"
            ),
            DeclareLaunchArgument(
                "stt_backend", default_value="mock", description="mock | whisper | faster_whisper"
            ),
            DeclareLaunchArgument(
                "stt_model_size", default_value="base", description="tiny|base|small|medium|large"
            ),
            DeclareLaunchArgument(
                "stt_model_dir", default_value="", description="Absolute path to STT model cache"
            ),
            DeclareLaunchArgument(
                "diarization_enabled", default_value="false", description="Enable pyannote"
            ),
            DeclareLaunchArgument(
                "diarization_hf_token",
                default_value="",
                description="HuggingFace token for pyannote (gated model, requires ToS accept)",
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
            behavior_engine,
            tts,
        ]
    )
