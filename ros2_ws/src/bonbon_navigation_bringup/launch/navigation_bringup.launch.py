"""navigation_bringup.launch.py — full Pi-3 (Navigation/Motion/Safety) bringup.

Composes existing per-subsystem launch files in the boot order specified
by config/distributed/pi_navigation_safety.yaml. Launches NO new node
types itself -- every node here already exists and is independently
tested; this file is composition + correct Pi-3-only HAL scoping only.

Explicitly launches ONLY lidar/motor/servo/stepper/estop/imu/battery HAL
devices (camera/mic/speaker are Pi-2 hardware) -- mirrors
bonbon_human_ai_bringup's Pi-2 exclusion pattern exactly, so this launch
can never accidentally start Pi-2 hardware nodes on Pi-3.

Boot order (safety-critical -- safety_gate_node/estop MUST be up before
any HAL actuator node can be commanded):
  1. bonbon_safety (safety_supervisor, safety_gate, watchdog, estop)
  2. bonbon_hal (lidar/motor/servo/stepper/estop/imu/battery)
  3. bonbon_base_controller (diff-drive kinematics over motor_node)
  4. bonbon_actuation (gesture execution, gated through safety_gate_node)
  5. bonbon_motion_approval_gateway (proposal -> approved-command chain)
  6. bonbon_navigation (Nav2 + RTAB-Map localization)
  7. Cross-Pi liveness + authority (self_id=pi3)

Usage:
  ros2 launch bonbon_navigation_bringup navigation_bringup.launch.py driver_mode:=real
  ros2 launch bonbon_navigation_bringup navigation_bringup.launch.py   # mock, dev/CI
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
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
    simulation = LaunchConfiguration("simulation")
    overrides = os.path.join(
        get_package_share_directory("bonbon_navigation_bringup"),
        "config",
        "pi3_hal_overrides.yaml",
    )

    # ── Rank 1: safety subsystem FIRST -- safety_gate_node is the sole
    #    gated-actuation path and must exist before any HAL actuator node
    #    starts commanding hardware (see bonbon_safety/safety.launch.py) ──
    safety = _include("bonbon_safety", "safety.launch.py", {"simulation": simulation})

    # ── Rank 2: HAL -- lidar/motor/servo/stepper/estop/imu/battery ONLY
    #    (camera/mic/speaker are Pi-2 hardware, excluded) ─────────────────
    hal = _include(
        "bonbon_hal",
        "hal.launch.py",
        {
            "driver_mode": driver_mode,
            "override_params_file": overrides,
            "launch_camera": "false",
            "launch_mic": "false",
            "launch_speaker": "false",
            "launch_lidar": "true",
            "launch_motor": "true",
            "launch_servo": "true",
            "launch_stepper": "true",
            "launch_estop": "true",
            "launch_imu": "true",
            "launch_battery": "true",
        },
    )

    # ── Rank 3: base_controller (diff-drive kinematics over motor_node) ──
    base_controller = _include("bonbon_base_controller", "base_controller.launch.py")

    # ── Rank 4: actuation (gestures, gated through safety_gate_node) ─────
    actuation = _include("bonbon_actuation", "actuation.launch.py")

    # ── Rank 5: motion approval gateway (proposal -> approved command) ───
    motion_gateway = _include("bonbon_motion_approval_gateway", "motion_approval_gateway.launch.py")

    # ── Rank 6: navigation (Nav2 + RTAB-Map localization) ────────────────
    navigation = _include("bonbon_navigation", "navigation.launch.py")

    # ── Cross-Pi liveness + authority (self_id=pi3, see
    #    bonbon_distributed_safety / bonbon_authority_manager) ───────────
    distributed_safety = LifecycleNode(
        package="bonbon_distributed_safety",
        executable="distributed_safety_node",
        name="distributed_safety_node",
        namespace="",
        parameters=[{"self_id": "pi3"}],
        output="screen",
    )
    authority_manager = LifecycleNode(
        package="bonbon_authority_manager",
        executable="authority_manager_node",
        name="authority_manager_node",
        namespace="",
        parameters=[{"self_id": "pi3"}],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "driver_mode", default_value="mock", description="real|mock — HAL driver mode"
            ),
            DeclareLaunchArgument(
                "simulation",
                default_value="false",
                description="Set true to enable MockGPIO in bonbon_safety's estop_node "
                "(no physical GPIO access)",
            ),
            safety,
            hal,
            distributed_safety,
            authority_manager,
            base_controller,
            actuation,
            motion_gateway,
            navigation,
        ]
    )
