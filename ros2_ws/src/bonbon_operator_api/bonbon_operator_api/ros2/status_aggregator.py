"""RobotStatusAggregator — thread-safe snapshot of all robot subsystem states.

Receives callbacks from ROS2DashboardBridge and merges updates into a single
``RobotStatus`` snapshot.  Readers call ``get_status()`` from any thread.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from bonbon_operator_api.models.robot_models import (
    ActuationData,
    BatteryData,
    ModuleStatus,
    NavigationData,
    PerceptionData,
    RobotStatus,
    SafetyStateData,
    TTSData,
)

logger = logging.getLogger(__name__)

# How long without any update before robot is considered offline (seconds)
_OFFLINE_TIMEOUT_SEC = 15.0


class RobotStatusAggregator:
    """Thread-safe aggregator of ROS2 robot status data.

    Updated by ``ROS2DashboardBridge`` callbacks; read by API handlers.

    Parameters
    ----------
    offline_timeout_sec:
        Seconds of silence before ``is_online`` flips to False.
    """

    def __init__(self, offline_timeout_sec: float = _OFFLINE_TIMEOUT_SEC) -> None:
        self._lock = threading.RLock()
        self._offline_timeout = offline_timeout_sec
        self._start_time = time.monotonic()

        # Mutable snapshot fields — updated by bridge callbacks
        self._safety = SafetyStateData(
            state="unknown",
            active_faults=[],
            last_event_ts=None,
            watchdog_ok=True,
        )
        self._battery = BatteryData(
            voltage_v=0.0,
            percentage=0.0,
            is_charging=False,
            estimated_runtime_min=None,
        )
        self._navigation = NavigationData(
            state="idle",
            current_x=0.0,
            current_y=0.0,
            current_yaw=0.0,
            goal_x=None,
            goal_y=None,
            progress_pct=None,
            active_map=None,
        )
        self._perception = PerceptionData(
            camera_active=False,
            lidar_active=False,
            persons_detected=0,
            obstacle_distance_m=None,
        )
        self._tts = TTSData(
            is_speaking=False,
            current_text=None,
            queue_depth=0,
        )
        self._actuation = ActuationData(
            linear_velocity_mps=0.0,
            angular_velocity_rps=0.0,
            motors_enabled=False,
        )
        self._modules: dict[str, ModuleStatus] = {}
        self._active_task: str | None = None
        self._last_updated: float = 0.0  # epoch seconds; 0 = never heard from robot

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_status(self) -> RobotStatus:
        """Return an immutable snapshot of the current robot status."""
        with self._lock:
            now = time.time()
            uptime = time.monotonic() - self._start_time
            is_online = (
                self._last_updated > 0 and (now - self._last_updated) < self._offline_timeout
            )
            return RobotStatus(
                is_online=is_online,
                uptime_sec=uptime,
                safety=self._safety.model_copy(),
                battery=self._battery.model_copy(),
                navigation=self._navigation.model_copy(),
                perception=self._perception.model_copy(),
                tts=self._tts.model_copy(),
                actuation=self._actuation.model_copy(),
                modules={k: v.model_copy() for k, v in self._modules.items()},
                active_task=self._active_task,
                last_updated=self._last_updated,
            )

    def is_online(self) -> bool:
        with self._lock:
            return (
                self._last_updated > 0
                and (time.time() - self._last_updated) < self._offline_timeout
            )

    def get_safety_state(self) -> str:
        with self._lock:
            return self._safety.state

    # ------------------------------------------------------------------
    # Write API — called from bridge callbacks (background ROS2 thread)
    # ------------------------------------------------------------------

    def update_safety(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._safety = SafetyStateData(
                state=data.get("state", self._safety.state),
                active_faults=data.get("active_faults", self._safety.active_faults),
                last_event_ts=data.get("last_event_ts", self._safety.last_event_ts),
                watchdog_ok=data.get("watchdog_ok", self._safety.watchdog_ok),
            )
            self._touch()

    def update_battery(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._battery = BatteryData(
                voltage_v=data.get("voltage_v", self._battery.voltage_v),
                percentage=data.get("percentage", self._battery.percentage),
                is_charging=data.get("is_charging", self._battery.is_charging),
                estimated_runtime_min=data.get(
                    "estimated_runtime_min", self._battery.estimated_runtime_min
                ),
            )
            self._touch()

    def update_navigation(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._navigation = NavigationData(
                state=data.get("state", self._navigation.state),
                current_x=data.get("current_x", self._navigation.current_x),
                current_y=data.get("current_y", self._navigation.current_y),
                current_yaw=data.get("current_yaw", self._navigation.current_yaw),
                goal_x=data.get("goal_x", self._navigation.goal_x),
                goal_y=data.get("goal_y", self._navigation.goal_y),
                progress_pct=data.get("progress_pct", self._navigation.progress_pct),
                active_map=data.get("active_map", self._navigation.active_map),
            )
            self._touch()

    def update_perception(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._perception = PerceptionData(
                camera_active=data.get("camera_active", self._perception.camera_active),
                lidar_active=data.get("lidar_active", self._perception.lidar_active),
                persons_detected=data.get("persons_detected", self._perception.persons_detected),
                obstacle_distance_m=data.get(
                    "obstacle_distance_m", self._perception.obstacle_distance_m
                ),
            )
            self._touch()

    def update_tts(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._tts = TTSData(
                is_speaking=data.get("is_speaking", self._tts.is_speaking),
                current_text=data.get("current_text", self._tts.current_text),
                queue_depth=data.get("queue_depth", self._tts.queue_depth),
            )
            self._touch()

    def update_actuation(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._actuation = ActuationData(
                linear_velocity_mps=data.get(
                    "linear_velocity_mps", self._actuation.linear_velocity_mps
                ),
                angular_velocity_rps=data.get(
                    "angular_velocity_rps", self._actuation.angular_velocity_rps
                ),
                motors_enabled=data.get("motors_enabled", self._actuation.motors_enabled),
            )
            self._touch()

    def update_module(self, module_name: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._modules[module_name] = ModuleStatus(
                name=module_name,
                state=data.get("state", "unknown"),
                health=data.get("health", "unknown"),
                message=data.get("message", ""),
            )
            self._touch()

    def update_active_task(self, task_id: str | None) -> None:
        with self._lock:
            self._active_task = task_id
            self._touch()

    def mark_heartbeat(self) -> None:
        """Record that the robot is alive (e.g., from a heartbeat topic)."""
        with self._lock:
            self._touch()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _touch(self) -> None:
        """Update the last_updated timestamp (must be called under lock)."""
        self._last_updated = time.time()
