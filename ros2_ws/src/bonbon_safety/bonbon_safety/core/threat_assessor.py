"""
bonbon_safety.core.threat_assessor
=====================================
Converts raw ROS2 topic data into a SensorSnapshot for the FSM.

This class is the single point that knows *which ROS2 topics map to which
sensor fields*.  The supervisor node calls `update_*()` methods as messages
arrive, then calls `build_snapshot()` at each 10 Hz cycle.

Staleness detection is handled here — if a topic has not been received within
its expected maximum interval, the corresponding health flag is set.

No ROS2 imports — only Python stdlib and safety core types.  Tests can feed
data directly without spinning up a ROS2 node.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from bonbon_safety.core.safety_state_machine import SensorSnapshot

logger = logging.getLogger(__name__)


@dataclass
class ThreatAssessorConfig:
    """Maximum age (seconds) before a sensor reading is considered stale."""

    lidar_max_age_sec: float = 0.5  # RPLIDAR S2 at 10 Hz → expect every 0.1s
    imu_max_age_sec: float = 0.1  # 100 Hz IMU
    camera_max_age_sec: float = 0.2  # 30 Hz camera; 2 missed frames = stale
    battery_max_age_sec: float = 5.0  # BMS publishes slowly
    servo_max_age_sec: float = 0.5  # Dynamixel state at 20 Hz
    person_max_age_sec: float = 1.0  # Perception fusion tracks up to 1s after last detection
    imu_drift_threshold_rads: float = 0.1  # rad/s angular drift

    def __post_init__(self) -> None:
        for field_name in (
            "lidar_max_age_sec",
            "imu_max_age_sec",
            "camera_max_age_sec",
            "battery_max_age_sec",
            "servo_max_age_sec",
            "person_max_age_sec",
        ):
            val = getattr(self, field_name)
            if val < 0:
                raise ValueError(f"ThreatAssessorConfig.{field_name} must be >= 0, got {val}")


class ThreatAssessor:
    """
    Aggregates sensor data into a SensorSnapshot.

    All update methods are called from ROS2 subscriber callbacks and are
    lightweight (just store the value + timestamp).

    `build_snapshot()` is called once per supervisor cycle from the timer
    callback and applies staleness checks.
    """

    def __init__(self, config: ThreatAssessorConfig | None = None) -> None:
        self._cfg = config or ThreatAssessorConfig()
        self._reset_state()

    def _reset_state(self) -> None:
        # Sensor values (last received)
        self._nearest_obstacle_m: float = -1.0
        self._nearest_human_m: float = -1.0
        self._cliff_left: bool = False
        self._cliff_right: bool = False
        self._bumper_front: bool = False
        self._bumper_rear: bool = False
        self._imu_angular_velocity_norm: float = 0.0  # rad/s magnitude
        self._battery_percent: float = 100.0
        self._cpu_temp_c: float = 20.0
        self._motor_temp_c: float = 20.0
        self._servo_fault: bool = False
        self._odrive_fault: bool = False
        self._estop_hardware: bool = False
        self._unsafe_command: bool = False
        self._navigation_timeout: bool = False
        self._critical_node_crashed: bool = False
        self._important_node_crashed: bool = False

        # Last-update timestamps (0 = never received)
        self._t_lidar: float = 0.0
        self._t_imu: float = 0.0
        self._t_camera: float = 0.0
        self._t_battery: float = 0.0
        self._t_servo: float = 0.0
        self._t_person: float = 0.0

    # ── Update methods (called from ROS2 subscriber callbacks) ───────────────

    def update_lidar_scan(
        self,
        nearest_obstacle_m: float,
        *,
        has_cliff_left: bool = False,
        has_cliff_right: bool = False,
        timestamp: float | None = None,
    ) -> None:
        """
        Called when a new LaserScan message arrives.

        Parameters
        ----------
        nearest_obstacle_m:
            Minimum range in the scan (already filtered for noise/glass).
            Pass -1.0 if the scan data is invalid.
        timestamp:
            Optional ROS2 message timestamp (seconds).  If not provided,
            the current monotonic time is used.
        """
        self._nearest_obstacle_m = nearest_obstacle_m
        self._cliff_left = has_cliff_left
        self._cliff_right = has_cliff_right
        self._t_lidar = timestamp if timestamp is not None else time.monotonic()

    def update_imu(
        self,
        angular_velocity_norm_rads: float = 0.0,
        *,
        angular_velocity_z: float | None = None,
        linear_accel_x: float = 0.0,
        linear_accel_y: float = 0.0,
        linear_accel_z: float = 9.81,
        timestamp: float | None = None,
    ) -> None:
        """
        Called when a new Imu message arrives.

        Accepts either the pre-computed angular velocity norm or individual
        axis values (angular_velocity_z is used as the primary signal when
        provided; full 3-axis norm can be computed by callers if needed).

        Parameters
        ----------
        angular_velocity_norm_rads:
            |omega| in rad/s (positional, legacy parameter).
        angular_velocity_z:
            Z-axis angular velocity in rad/s (yaw rate).  When provided,
            it is used as the norm estimate for drift detection.
        linear_accel_*:
            Linear acceleration components (currently stored for future use).
        timestamp:
            Optional source timestamp; defaults to monotonic time.
        """
        if angular_velocity_z is not None:
            self._imu_angular_velocity_norm = abs(angular_velocity_z)
        else:
            self._imu_angular_velocity_norm = angular_velocity_norm_rads
        self._t_imu = timestamp if timestamp is not None else time.monotonic()

    def update_camera(self) -> None:
        """Called when any camera frame is successfully processed."""
        self._t_camera = time.monotonic()

    def update_persons(
        self,
        persons,
        *,
        timestamp: float | None = None,
    ) -> None:
        """
        Called by perception fusion with tracked person data.

        Parameters
        ----------
        persons:
            Either a float (nearest_human_m legacy value), or a list of
            dicts with ``track_id`` and ``distance_m`` keys.
            Pass an empty list (or -1.0) when no persons are tracked.
        timestamp:
            Optional source timestamp; defaults to monotonic time.
        """
        if isinstance(persons, (int, float)):
            # Legacy float interface: nearest_human_m directly
            self._nearest_human_m = float(persons)
        elif isinstance(persons, list):
            if persons:
                self._nearest_human_m = min(float(p.get("distance_m", -1.0)) for p in persons)
            else:
                self._nearest_human_m = -1.0
        else:
            self._nearest_human_m = -1.0
        self._t_person = timestamp if timestamp is not None else time.monotonic()

    def update_bumpers(self, front: bool, rear: bool) -> None:
        self._bumper_front = front
        self._bumper_rear = rear

    def update_cliff_sensors(self, left: bool, right: bool) -> None:
        self._cliff_left = left
        self._cliff_right = right

    def update_battery(
        self,
        percent: float,
        *,
        voltage_v: float = 0.0,
        current_a: float = 0.0,
    ) -> None:
        """
        Update battery state.

        Parameters
        ----------
        percent:    State-of-charge percentage 0–100.
        voltage_v:  Pack voltage (stored for future diagnostics; not currently used).
        current_a:  Pack current in amps (negative = discharging).
        """
        self._battery_percent = max(0.0, min(100.0, percent))
        self._t_battery = time.monotonic()

    def update_temperature(
        self,
        cpu_temp_c: float,
        motor_temp_c: float,
        *,
        battery_temp_c: float = 25.0,
    ) -> None:
        """
        Update temperature readings.

        Parameters
        ----------
        cpu_temp_c:     SoC CPU temperature in °C.
        motor_temp_c:   Highest drive-motor winding temperature in °C.
        battery_temp_c: Battery pack temperature (stored for future diagnostics).
        """
        self._cpu_temp_c = cpu_temp_c
        self._motor_temp_c = motor_temp_c

    def update_servo_state(self, fault: bool) -> None:
        self._servo_fault = fault
        self._t_servo = time.monotonic()

    def update_odrive_state(self, fault: bool) -> None:
        self._odrive_fault = fault

    def update_estop(self, pressed: bool) -> None:
        """Called by the e-stop node — this transition is NEVER debounced."""
        if pressed and not self._estop_hardware:
            logger.critical("Hardware e-stop button PRESSED")
        self._estop_hardware = pressed

    def update_unsafe_command(self, detected: bool) -> None:
        """Set by the LLM safety filter when a command fails whitelist check."""
        if detected:
            logger.warning("Unsafe command flag set by LLM safety filter")
        self._unsafe_command = detected

    def update_navigation_timeout(self, timed_out: bool) -> None:
        self._navigation_timeout = timed_out

    def update_node_health(self, critical_crashed: bool, important_crashed: bool) -> None:
        self._critical_node_crashed = critical_crashed
        self._important_node_crashed = important_crashed

    # ── Snapshot builder ─────────────────────────────────────────────────────

    def build_snapshot(self) -> SensorSnapshot:
        """
        Build a SensorSnapshot from the current accumulated state.
        Called once per 10 Hz supervisor cycle.

        Staleness is evaluated here so the FSM never sees old data silently.
        """
        now = time.monotonic()

        # Staleness checks — treat never-received as stale
        lidar_stale = (
            (now - self._t_lidar) > self._cfg.lidar_max_age_sec if self._t_lidar > 0 else True
        )
        imu_stale = (now - self._t_imu) > self._cfg.imu_max_age_sec if self._t_imu > 0 else True
        camera_stale = (
            (now - self._t_camera) > self._cfg.camera_max_age_sec if self._t_camera > 0 else True
        )

        # If person data is stale, we cannot rely on nearest_human_m
        person_stale = (
            (now - self._t_person) > self._cfg.person_max_age_sec if self._t_person > 0 else True
        )
        nearest_human = -1.0 if person_stale else self._nearest_human_m

        # IMU drift: only meaningful if IMU data is fresh
        imu_drift = (not imu_stale) and (
            self._imu_angular_velocity_norm > self._cfg.imu_drift_threshold_rads
        )

        if lidar_stale and self._t_lidar > 0:
            logger.warning(
                "LIDAR stale: %.2f s since last scan (max %.2f s)",
                now - self._t_lidar,
                self._cfg.lidar_max_age_sec,
            )
        if imu_stale and self._t_imu > 0:
            logger.warning(
                "IMU stale: %.2f s since last reading (max %.2f s)",
                now - self._t_imu,
                self._cfg.imu_max_age_sec,
            )

        return SensorSnapshot(
            nearest_obstacle_m=self._nearest_obstacle_m if not lidar_stale else -1.0,
            nearest_human_m=nearest_human,
            cliff_detected_left=self._cliff_left,
            cliff_detected_right=self._cliff_right,
            bumper_front=self._bumper_front,
            bumper_rear=self._bumper_rear,
            lidar_stale=lidar_stale,
            camera_stale=camera_stale,
            imu_stale=imu_stale,
            imu_drift_detected=imu_drift,
            battery_percent=self._battery_percent,
            cpu_temp_c=self._cpu_temp_c,
            motor_temp_c=self._motor_temp_c,
            servo_fault=self._servo_fault,
            odrive_fault=self._odrive_fault,
            estop_hardware=self._estop_hardware,
            unsafe_command_detected=self._unsafe_command,
            navigation_timeout=self._navigation_timeout,
            critical_node_crashed=self._critical_node_crashed,
            important_node_crashed=self._important_node_crashed,
            timestamp=now,
        )

    def reset_transient_flags(self) -> None:
        """
        Clear one-shot flags after the FSM has processed them.
        Called at end of each supervisor cycle.

        Flags like bumper contact are cleared after one cycle so the FSM
        can detect the *rising edge* rather than holding DANGER indefinitely
        for a brief bump.  The FSM's hysteresis handles the recovery timing.
        """
        self._unsafe_command = False
        self._navigation_timeout = False
        # Note: bumpers and e-stop are NOT cleared here — they hold their
        # state until the next hardware message updates them.
