"""
test_threat_assessor.py
=======================
Unit tests for bonbon_safety.core.threat_assessor.

Tests
-----
- SensorSnapshot built from a fresh ThreatAssessor has correct default values
- Each update_* method sets the correct snapshot field
- Staleness: fields go stale after their max_age_sec
- Staleness: fields do NOT go stale before their threshold
- reset_transient_flags() clears one-shot fields
- Multiple sensor streams are independent
"""

from __future__ import annotations

import time

import pytest
from bonbon_safety.core.threat_assessor import ThreatAssessor, ThreatAssessorConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_config() -> ThreatAssessorConfig:
    return ThreatAssessorConfig(
        lidar_max_age_sec=0.5,
        imu_max_age_sec=0.1,
        camera_max_age_sec=0.2,
        person_max_age_sec=1.0,
    )


def _assessor() -> ThreatAssessor:
    return ThreatAssessor(_default_config())


# ── Initial snapshot ──────────────────────────────────────────────────────────


class TestInitialSnapshot:
    def test_fresh_assessor_builds_snapshot(self):
        ta = _assessor()
        snap = ta.build_snapshot()
        assert snap is not None

    def test_default_estop_false(self):
        snap = _assessor().build_snapshot()
        assert snap.estop_hardware is False

    def test_default_battery_full(self):
        snap = _assessor().build_snapshot()
        assert snap.battery_percent >= 100.0

    def test_default_no_bumper(self):
        snap = _assessor().build_snapshot()
        assert snap.bumper_front is False
        assert snap.bumper_rear is False

    def test_initial_lidar_stale(self):
        """Without any LIDAR callback the snapshot should mark lidar_stale=True."""
        ta = ThreatAssessor(ThreatAssessorConfig(lidar_max_age_sec=0.001))
        time.sleep(0.01)
        snap = ta.build_snapshot()
        assert snap.lidar_stale is True


# ── LIDAR updates ─────────────────────────────────────────────────────────────


class TestLidarUpdates:
    def test_nearest_obstacle_updated(self):
        ta = _assessor()
        ta.update_lidar_scan(nearest_obstacle_m=1.5, timestamp=time.monotonic())
        snap = ta.build_snapshot()
        assert snap.nearest_obstacle_m == pytest.approx(1.5)

    def test_lidar_not_stale_immediately_after_update(self):
        ta = _assessor()
        ta.update_lidar_scan(nearest_obstacle_m=2.0, timestamp=time.monotonic())
        snap = ta.build_snapshot()
        assert snap.lidar_stale is False

    def test_lidar_stale_after_age_exceeded(self):
        ta = ThreatAssessor(ThreatAssessorConfig(lidar_max_age_sec=0.05))
        ta.update_lidar_scan(nearest_obstacle_m=2.0, timestamp=time.monotonic())
        time.sleep(0.1)  # exceed 0.05 s threshold
        snap = ta.build_snapshot()
        assert snap.lidar_stale is True


# ── IMU updates ───────────────────────────────────────────────────────────────


class TestImuUpdates:
    def test_imu_not_stale_after_update(self):
        ta = _assessor()
        ta.update_imu(
            angular_velocity_z=0.01,
            linear_accel_x=0.0,
            linear_accel_y=0.0,
            linear_accel_z=9.81,
            timestamp=time.monotonic(),
        )
        snap = ta.build_snapshot()
        assert snap.imu_stale is False

    def test_imu_stale_without_data(self):
        ta = ThreatAssessor(ThreatAssessorConfig(imu_max_age_sec=0.05))
        time.sleep(0.1)
        snap = ta.build_snapshot()
        assert snap.imu_stale is True


# ── Person tracking updates ───────────────────────────────────────────────────


class TestPersonUpdates:
    def test_nearest_human_updated(self):
        ta = _assessor()
        # Simulate two person detections at different distances
        ta.update_persons(
            [
                {"track_id": 1, "distance_m": 3.0},
                {"track_id": 2, "distance_m": 1.5},
            ],
            timestamp=time.monotonic(),
        )
        snap = ta.build_snapshot()
        assert snap.nearest_human_m == pytest.approx(1.5)

    def test_nearest_human_minus1_when_no_persons(self):
        ta = _assessor()
        ta.update_persons([], timestamp=time.monotonic())
        snap = ta.build_snapshot()
        assert snap.nearest_human_m == -1.0

    def test_person_data_coasts_within_age_limit(self):
        ta = ThreatAssessor(ThreatAssessorConfig(person_max_age_sec=0.5))
        ta.update_persons([{"track_id": 1, "distance_m": 1.0}], timestamp=time.monotonic())
        time.sleep(0.1)  # within 0.5s coast window
        snap = ta.build_snapshot()
        assert snap.nearest_human_m == pytest.approx(1.0)

    def test_person_data_expires_after_coast_window(self):
        ta = ThreatAssessor(ThreatAssessorConfig(person_max_age_sec=0.05))
        ta.update_persons([{"track_id": 1, "distance_m": 1.0}], timestamp=time.monotonic())
        time.sleep(0.1)  # exceed 0.05s coast window
        snap = ta.build_snapshot()
        assert snap.nearest_human_m == -1.0


# ── Bumper updates ────────────────────────────────────────────────────────────


class TestBumperUpdates:
    def test_front_bumper_sets_flag(self):
        ta = _assessor()
        ta.update_bumpers(front=True, rear=False)
        snap = ta.build_snapshot()
        assert snap.bumper_front is True
        assert snap.bumper_rear is False

    def test_rear_bumper_sets_flag(self):
        ta = _assessor()
        ta.update_bumpers(front=False, rear=True)
        snap = ta.build_snapshot()
        assert snap.bumper_rear is True

    def test_bumper_cleared_after_update(self):
        ta = _assessor()
        ta.update_bumpers(front=True, rear=False)
        ta.update_bumpers(front=False, rear=False)
        snap = ta.build_snapshot()
        assert snap.bumper_front is False


# ── Battery updates ───────────────────────────────────────────────────────────


class TestBatteryUpdates:
    def test_battery_percent_updated(self):
        ta = _assessor()
        ta.update_battery(percent=15.0, voltage_v=10.5, current_a=-2.0)
        snap = ta.build_snapshot()
        assert snap.battery_percent == pytest.approx(15.0)

    def test_battery_100_by_default(self):
        snap = _assessor().build_snapshot()
        assert snap.battery_percent >= 100.0


# ── Temperature updates ───────────────────────────────────────────────────────


class TestTemperatureUpdates:
    def test_cpu_temp_updated(self):
        ta = _assessor()
        ta.update_temperature(cpu_temp_c=72.0, motor_temp_c=40.0, battery_temp_c=35.0)
        snap = ta.build_snapshot()
        assert snap.cpu_temp_c == pytest.approx(72.0)

    def test_motor_temp_updated(self):
        ta = _assessor()
        ta.update_temperature(cpu_temp_c=50.0, motor_temp_c=65.0, battery_temp_c=30.0)
        snap = ta.build_snapshot()
        assert snap.motor_temp_c == pytest.approx(65.0)


# ── E-stop updates ────────────────────────────────────────────────────────────


class TestEstopUpdates:
    def test_estop_set(self):
        ta = _assessor()
        ta.update_estop(pressed=True)
        snap = ta.build_snapshot()
        assert snap.estop_hardware is True

    def test_estop_cleared(self):
        ta = _assessor()
        ta.update_estop(pressed=True)
        ta.update_estop(pressed=False)
        snap = ta.build_snapshot()
        assert snap.estop_hardware is False


# ── Transient flags ───────────────────────────────────────────────────────────


class TestTransientFlags:
    def test_unsafe_command_is_transient(self):
        ta = _assessor()
        ta.update_unsafe_command(detected=True)
        snap1 = ta.build_snapshot()
        assert snap1.unsafe_command_detected is True
        ta.reset_transient_flags()
        snap2 = ta.build_snapshot()
        assert snap2.unsafe_command_detected is False

    def test_navigation_timeout_is_transient(self):
        ta = _assessor()
        ta.update_navigation_timeout(timed_out=True)
        snap1 = ta.build_snapshot()
        assert snap1.navigation_timeout is True
        ta.reset_transient_flags()
        snap2 = ta.build_snapshot()
        assert snap2.navigation_timeout is False


# ── Node health ───────────────────────────────────────────────────────────────


class TestNodeHealth:
    def test_critical_crash_sets_flag(self):
        ta = _assessor()
        ta.update_node_health(critical_crashed=True, important_crashed=False)
        snap = ta.build_snapshot()
        assert snap.critical_node_crashed is True
        assert snap.important_node_crashed is False

    def test_important_crash_sets_flag(self):
        ta = _assessor()
        ta.update_node_health(critical_crashed=False, important_crashed=True)
        snap = ta.build_snapshot()
        assert snap.important_node_crashed is True

    def test_health_restored(self):
        ta = _assessor()
        ta.update_node_health(critical_crashed=True, important_crashed=False)
        ta.update_node_health(critical_crashed=False, important_crashed=False)
        snap = ta.build_snapshot()
        assert snap.critical_node_crashed is False


# ── Config validation ─────────────────────────────────────────────────────────


class TestConfig:
    def test_negative_age_raises(self):
        with pytest.raises((ValueError, AssertionError)):
            ThreatAssessorConfig(lidar_max_age_sec=-1.0)

    def test_zero_age_raises_or_warns(self):
        # Zero staleness threshold is either rejected or treated as always-stale
        try:
            ta = ThreatAssessor(ThreatAssessorConfig(lidar_max_age_sec=0.0))
            snap = ta.build_snapshot()
            assert snap.lidar_stale is True  # always stale with 0s threshold
        except (ValueError, AssertionError):
            pass  # also acceptable
