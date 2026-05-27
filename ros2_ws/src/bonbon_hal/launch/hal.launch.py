"""
hal.launch.py
==============
Launches all BonBon HAL hardware nodes.

Usage
-----
  # Simulation (MockDrivers, no real hardware)
  ros2 launch bonbon_hal hal.launch.py

  # Full hardware
  ros2 launch bonbon_hal hal.launch.py driver_mode:=real

  # Hardware with site overrides
  ros2 launch bonbon_hal hal.launch.py driver_mode:=real \\
      override_params_file:=/etc/bonbon/site_hal.yaml

  # Partial: only LIDAR + IMU in real mode
  ros2 launch bonbon_hal hal.launch.py driver_mode:=real \\
      launch_camera:=false launch_mic:=false launch_speaker:=false

  # Simulation with BONBON_SIMULATION env for GPIO mock
  ros2 launch bonbon_hal hal.launch.py simulation:=true
"""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode


def _hal_nodes(context, *args, **kwargs) -> list:
    pkg = get_package_share_directory("bonbon_hal")
    base_params = os.path.join(pkg, "config", "hal_params.yaml")

    driver_mode = context.launch_configurations.get("driver_mode", "mock")
    override_file = context.launch_configurations.get("override_params_file", "")

    def _make_node(name, pkg_=None) -> LifecycleNode:
        params = [
            base_params,
            {name: {"ros__parameters": {"driver_mode": driver_mode}}},
        ]
        if override_file:
            params.append(override_file)
        return LifecycleNode(
            package="bonbon_hal",
            executable=name,
            name=name,
            namespace="/bonbon",
            parameters=params,
            output="screen",
            emulate_tty=True,
            respawn=True,
            respawn_delay=2.0,
        )

    launch_camera = context.launch_configurations.get("launch_camera", "true") == "true"
    launch_lidar = context.launch_configurations.get("launch_lidar", "true") == "true"
    launch_imu = context.launch_configurations.get("launch_imu", "true") == "true"
    launch_servo = context.launch_configurations.get("launch_servo", "true") == "true"
    launch_battery = context.launch_configurations.get("launch_battery", "true") == "true"
    launch_mic = context.launch_configurations.get("launch_mic", "true") == "true"
    launch_speaker = context.launch_configurations.get("launch_speaker", "true") == "true"
    launch_estop = context.launch_configurations.get("launch_estop", "true") == "true"

    nodes = []
    if launch_camera:
        nodes.append(_make_node("camera_node"))
    if launch_lidar:
        nodes.append(_make_node("lidar_node"))
    if launch_imu:
        nodes.append(_make_node("imu_node"))
    if launch_servo:
        nodes.append(_make_node("servo_node"))
    if launch_battery:
        nodes.append(_make_node("battery_node"))
    if launch_mic:
        nodes.append(_make_node("mic_node"))
    if launch_speaker:
        nodes.append(_make_node("speaker_node"))
    if launch_estop:
        # Estop node: shorter respawn (1s), higher priority
        params = [
            base_params,
            {"estop_hal_node": {"ros__parameters": {"driver_mode": driver_mode}}},
        ]
        if override_file:
            params.append(override_file)
        nodes.append(
            LifecycleNode(
                package="bonbon_hal",
                executable="estop_hal_node",
                name="estop_hal_node",
                namespace="/bonbon",
                parameters=params,
                output="screen",
                emulate_tty=True,
                respawn=True,
                respawn_delay=1.0,
            )
        )
    return nodes


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "driver_mode", default_value="mock", description="real|mock — applies to all nodes"
            ),
            DeclareLaunchArgument(
                "simulation",
                default_value="false",
                description="Set BONBON_SIMULATION=1 (MockGPIO)",
            ),
            DeclareLaunchArgument(
                "override_params_file",
                default_value="",
                description="Site-specific parameter override YAML",
            ),
            DeclareLaunchArgument("launch_camera", default_value="true"),
            DeclareLaunchArgument("launch_lidar", default_value="true"),
            DeclareLaunchArgument("launch_imu", default_value="true"),
            DeclareLaunchArgument("launch_servo", default_value="true"),
            DeclareLaunchArgument("launch_battery", default_value="true"),
            DeclareLaunchArgument("launch_mic", default_value="true"),
            DeclareLaunchArgument("launch_speaker", default_value="true"),
            DeclareLaunchArgument("launch_estop", default_value="true"),
            DeclareLaunchArgument("log_level", default_value="info"),
            SetEnvironmentVariable(
                "BONBON_SIMULATION", "1", condition=IfCondition(LaunchConfiguration("simulation"))
            ),
            LogInfo(msg="[BonBon HAL] Launching hardware abstraction layer…"),
            OpaqueFunction(function=_hal_nodes),
        ]
    )
