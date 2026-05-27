"""
safety.launch.py
=================
Launches the complete BonBon safety subsystem:

  1. safety_supervisor_node  — 8-state FSM, 10 Hz evaluation, policy dispatcher
  2. safety_gate_node        — CLASS-A actuation gate (all commands pass through)
  3. watchdog_node           — 2 Hz heartbeat monitor for 14 managed nodes
  4. estop_node              — 50 Hz GPIO e-stop poller (simulation-safe)

Parameter override order (last wins):
  built-in defaults → safety_params.yaml → override_params_file launch arg

Usage
-----
  # Normal hardware launch
  ros2 launch bonbon_safety safety.launch.py

  # Simulation mode (MockGPIO, no real GPIO access)
  ros2 launch bonbon_safety safety.launch.py simulation:=true

  # Custom robot ID and parameter overrides
  ros2 launch bonbon_safety safety.launch.py robot_id:=bonbon-02 \\
      override_params_file:=/etc/bonbon/site_overrides.yaml

  # Custom policy file
  ros2 launch bonbon_safety safety.launch.py \\
      policy_file:=/etc/bonbon/hospital_policy.yaml

  # Tighter velocity cap (e.g., paediatric ward)
  ros2 launch bonbon_safety safety.launch.py caution_velocity_cap_mps:=0.2
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    LogInfo,
    OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def _safety_nodes(context, *args, **kwargs) -> list:
    """
    OpaqueFunction that resolves launch arguments at runtime and returns
    the three configured LifecycleNode actions.
    """
    pkg_share = get_package_share_directory("bonbon_safety")
    base_params = os.path.join(pkg_share, "config", "safety_params.yaml")

    robot_id = context.launch_configurations.get("robot_id", "bonbon-01")
    policy_file = context.launch_configurations.get("policy_file", "")
    override_file = context.launch_configurations.get("override_params_file", "")
    incident_db = context.launch_configurations.get(
        "incident_db_path", "/var/lib/bonbon/safety_incidents.db"
    )
    caution_vel_cap = float(context.launch_configurations.get("caution_velocity_cap_mps", "0.3"))
    gate_watchdog = float(context.launch_configurations.get("gate_watchdog_timeout_sec", "2.0"))

    # Build parameter list: base YAML first, then inline overrides,
    # then optional site override file.
    supervisor_params: list = [
        base_params,
        {
            "safety_supervisor_node": {
                "ros__parameters": {
                    "robot_id": robot_id,
                    "policy_file": policy_file,
                    "incident_db_path": incident_db,
                }
            }
        },
    ]
    if override_file:
        supervisor_params.append(override_file)

    watchdog_params: list = [base_params]
    if override_file:
        watchdog_params.append(override_file)

    estop_params: list = [base_params]
    if override_file:
        estop_params.append(override_file)

    # ── Safety gate parameters (shares base + optional overrides) ─────────────
    gate_params: list = [
        base_params,
        {
            "safety_gate_node": {
                "ros__parameters": {
                    "caution_velocity_cap_mps": caution_vel_cap,
                    "block_servos_in_danger": True,
                    "watchdog_timeout_sec": gate_watchdog,
                }
            }
        },
    ]
    if override_file:
        gate_params.append(override_file)

    nodes = [
        # ── Safety Supervisor ──────────────────────────────────────────────────
        LifecycleNode(
            package="bonbon_safety",
            executable="safety_supervisor_node",
            name="safety_supervisor_node",
            namespace="/bonbon",
            parameters=supervisor_params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
        ),
        # ── Safety Gate (CLASS-A CRITICAL — must start before HAL nodes) ──────
        LifecycleNode(
            package="bonbon_safety",
            executable="safety_gate_node",
            name="safety_gate_node",
            namespace="/bonbon",
            parameters=gate_params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=0.5,  # fastest restart: gate must never be absent
        ),
        # ── Watchdog ──────────────────────────────────────────────────────────
        LifecycleNode(
            package="bonbon_safety",
            executable="watchdog_node",
            name="watchdog_node",
            namespace="/bonbon",
            parameters=watchdog_params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
        ),
        # ── E-Stop ────────────────────────────────────────────────────────────
        LifecycleNode(
            package="bonbon_safety",
            executable="estop_node",
            name="estop_node",
            namespace="/bonbon",
            parameters=estop_params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=1.0,  # shorter: faster relay re-assertion on crash
        ),
    ]
    return nodes


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            # ── Launch arguments ──────────────────────────────────────────────────
            DeclareLaunchArgument(
                "simulation",
                default_value="false",
                description="Set true to enable MockGPIO (no physical GPIO access)",
            ),
            DeclareLaunchArgument(
                "robot_id",
                default_value="bonbon-01",
                description="Unique identifier for this physical unit (used in incident log)",
            ),
            DeclareLaunchArgument(
                "policy_file",
                default_value="",
                description="Absolute path to a custom safety_policy.yaml; "
                "leave empty to use the built-in default",
            ),
            DeclareLaunchArgument(
                "override_params_file",
                default_value="",
                description="Optional site-specific parameter override YAML "
                "(merged on top of safety_params.yaml)",
            ),
            DeclareLaunchArgument(
                "incident_db_path",
                default_value="/var/lib/bonbon/safety_incidents.db",
                description="Absolute path to the SQLite incident log database",
            ),
            DeclareLaunchArgument(
                "log_level",
                default_value="info",
                description="ROS2 log level: debug|info|warn|error|fatal",
            ),
            DeclareLaunchArgument(
                "caution_velocity_cap_mps",
                default_value="0.3",
                description="Max linear speed (m/s) when safety state is CAUTION "
                "(applied by safety_gate_node)",
            ),
            DeclareLaunchArgument(
                "gate_watchdog_timeout_sec",
                default_value="2.0",
                description="Seconds without a SafetyState heartbeat before the gate "
                "enters defensive mode (blocks all actuation)",
            ),
            # ── Simulation environment variable ───────────────────────────────────
            # Sets BONBON_SIMULATION=1 so estop_node uses MockGPIO.
            SetEnvironmentVariable(
                name="BONBON_SIMULATION",
                value="1",
                condition=IfCondition(LaunchConfiguration("simulation")),
            ),
            # ── Startup banner ────────────────────────────────────────────────────
            LogInfo(msg="[BonBon Safety] Launching safety subsystem…"),
            # ── Nodes (resolved via OpaqueFunction for runtime arg access) ────────
            OpaqueFunction(function=_safety_nodes),
        ]
    )
