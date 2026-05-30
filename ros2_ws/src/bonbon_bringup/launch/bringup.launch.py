"""
bonbon_bringup.bringup.launch.py
=================================
Top-level system bring-up for the BonBon service robot.

This is the launch file the Docker entrypoint and docker-compose files invoke:

    ros2 launch bonbon_bringup bringup.launch.py

It composes every subsystem's own launch file in a sensible startup order and
exposes launch arguments to select simulation/mock mode and to enable or
disable subsystem groups, so the same bring-up serves the real robot, the
Gazebo simulation, and CI smoke tests.

Startup order (each subsystem manages its own lifecycle internally)
-------------------------------------------------------------------
  1. data_stores   — persistence must be up before anything records to it
  2. safety        — the supervisor + e-stop come up before any actuator path
  3. hal           — hardware abstraction (real drivers or mocks)
  4. perception    — vision + speech sensing
  5. ai            — spatial, affective, gesture, perception_ai, llm
  6. behavior      — the central decision engine
  7. actuation     — expressive motion (gated by safety)
  8. navigation    — autonomous navigation (gated by safety)
  9. tts           — speech output
 10. operator_api  — dashboard / operator backend

Launch arguments
----------------
  simulation:=true|false      use mock HAL drivers and sim sensors (default false)
  enable_navigation:=bool     bring up navigation stack            (default true)
  enable_ai:=bool             bring up spatial/affective/gesture/llm (default true)
  enable_operator_api:=bool   bring up the dashboard backend       (default true)
  log_level:=info|debug|warn  ROS2 logger level for the group      (default info)

Examples
--------
  # Full real-robot stack
  ros2 launch bonbon_bringup bringup.launch.py

  # Headless simulation, no operator API (CI smoke)
  ros2 launch bonbon_bringup bringup.launch.py simulation:=true enable_operator_api:=false

  # Safety + HAL + perception only (sensor bring-up / calibration)
  ros2 launch bonbon_bringup bringup.launch.py enable_ai:=false \
      enable_navigation:=false enable_operator_api:=false
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    LogInfo,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression


def _include(package: str, launch_file: str, *, condition=None, args=None):
    """Build an IncludeLaunchDescription for ``<package>/launch/<launch_file>``.

    Missing launch files are tolerated at description-build time only if the
    package is installed; an absent package raises at launch, which is the
    desired fail-fast behaviour for a misconfigured deployment.
    """
    share = get_package_share_directory(package)
    path = os.path.join(share, "launch", launch_file)
    kwargs = {}
    if condition is not None:
        kwargs["condition"] = condition
    if args is not None:
        kwargs["launch_arguments"] = args
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(path), **kwargs)


def generate_launch_description() -> LaunchDescription:
    simulation = LaunchConfiguration("simulation")
    enable_navigation = LaunchConfiguration("enable_navigation")
    enable_ai = LaunchConfiguration("enable_ai")
    enable_operator_api = LaunchConfiguration("enable_operator_api")
    log_level = LaunchConfiguration("log_level")

    args = [
        DeclareLaunchArgument("simulation", default_value="false",
                              description="Use mock HAL drivers / simulated sensors."),
        DeclareLaunchArgument("enable_navigation", default_value="true",
                              description="Bring up the navigation stack."),
        DeclareLaunchArgument("enable_ai", default_value="true",
                              description="Bring up spatial/affective/gesture/perception_ai/llm."),
        DeclareLaunchArgument("enable_operator_api", default_value="true",
                              description="Bring up the operator/dashboard backend."),
        DeclareLaunchArgument("log_level", default_value="info",
                              description="ROS2 logger level for the bring-up group."),
    ]

    sim_args = {"simulation": simulation}

    # ── 1. Persistence ───────────────────────────────────────────────────────
    data_stores = _include("bonbon_data_stores", "data_stores.launch.py")

    # ── 2. Safety (always first among control paths) ─────────────────────────
    safety = _include("bonbon_safety", "safety.launch.py", args=sim_args)

    # ── 3. Hardware abstraction ──────────────────────────────────────────────
    hal = _include("bonbon_hal", "hal.launch.py", args=sim_args)

    # ── 4. Perception (sensing) ──────────────────────────────────────────────
    vision = _include("bonbon_vision", "vision.launch.py")
    speech = _include("bonbon_speech", "speech.launch.py")

    # ── 5. AI reasoning group ────────────────────────────────────────────────
    ai_group = GroupAction(
        condition=IfCondition(enable_ai),
        actions=[
            LogInfo(msg="bonbon_bringup: starting AI reasoning subsystems"),
            _include("bonbon_spatial", "spatial.launch.py"),
            _include("bonbon_affective_ai", "affective_ai.launch.py"),
            _include("bonbon_gesture", "gesture.launch.py"),
            _include("bonbon_perception_ai", "perception.launch.py"),
            _include("bonbon_llm", "llm.launch.py"),
        ],
    )

    # ── 6. Central decision engine ───────────────────────────────────────────
    behavior = _include("bonbon_behavior_engine", "behavior_engine.launch.py")

    # ── 7. Actuation (expressive motion, safety-gated) ───────────────────────
    actuation = _include("bonbon_actuation", "actuation.launch.py")

    # ── 8. Navigation (autonomous motion, safety-gated) ──────────────────────
    navigation = GroupAction(
        condition=IfCondition(enable_navigation),
        actions=[
            LogInfo(msg="bonbon_bringup: starting navigation stack"),
            _include("bonbon_navigation", "navigation.launch.py"),
        ],
    )

    # ── 9. Speech output ─────────────────────────────────────────────────────
    tts = _include("bonbon_tts", "tts.launch.py")

    # ── 10. Operator / dashboard backend ─────────────────────────────────────
    operator_api = GroupAction(
        condition=IfCondition(enable_operator_api),
        actions=[
            LogInfo(msg="bonbon_bringup: starting operator API"),
            _include("bonbon_operator_api", "operator_api.launch.py"),
        ],
    )

    return LaunchDescription([
        *args,
        LogInfo(msg=PythonExpression([
            "'bonbon_bringup: simulation=' + '", simulation, "'",
        ])),
        data_stores,
        safety,
        hal,
        vision,
        speech,
        ai_group,
        behavior,
        actuation,
        navigation,
        tts,
        operator_api,
    ])
