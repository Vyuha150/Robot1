"""
Tests for bonbon_navigation.core.localization_monitor
"""
import math
import time

import pytest

from bonbon_navigation.core.localization_monitor import (
    LocalizationMonitor,
    LocalizationQuality,
    LocalizationReport,
    PoseEstimate,
)


# ── PoseEstimate ──────────────────────────────────────────────────────────────

class TestPoseEstimate:
    def test_covariance_trace_computation(self):
        pe = PoseEstimate(
            x=1.0, y=2.0, yaw=0.5,
            cov_xx=0.01, cov_yy=0.02, cov_yawyaw=0.04,
        )
        assert pe.covariance_trace == pytest.approx(0.01 + 0.02 + 0.04)

    def test_default_covariance_zero(self):
        pe = PoseEstimate(x=0.0, y=0.0, yaw=0.0,
                          cov_xx=0.0, cov_yy=0.0, cov_yawyaw=0.0)
        assert pe.covariance_trace == 0.0

    def test_fields_stored_correctly(self):
        pe = PoseEstimate(x=3.14, y=-2.71, yaw=1.57,
                          cov_xx=0.005, cov_yy=0.005, cov_yawyaw=0.01)
        assert pe.x == pytest.approx(3.14)
        assert pe.y == pytest.approx(-2.71)
        assert pe.yaw == pytest.approx(1.57)


# ── Quality classification ────────────────────────────────────────────────────

class TestQualityClassification:
    def test_good_quality_low_covariance(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=1.0, y=2.0, yaw=0.0,
                        cov_xx=0.01, cov_yy=0.01, cov_yawyaw=0.02)
        assert mon.get_quality() == LocalizationQuality.GOOD

    def test_degraded_quality_medium_covariance(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=1.0, y=2.0, yaw=0.0,
                        cov_xx=0.05, cov_yy=0.05, cov_yawyaw=0.05)
        # trace = 0.15 → between 0.05 and 0.20 → DEGRADED
        assert mon.get_quality() == LocalizationQuality.DEGRADED

    def test_lost_quality_high_covariance(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=1.0, y=2.0, yaw=0.0,
                        cov_xx=0.10, cov_yy=0.10, cov_yawyaw=0.10)
        # trace = 0.30 > 0.20 → LOST
        assert mon.get_quality() == LocalizationQuality.LOST

    def test_unknown_before_first_update(self):
        mon = LocalizationMonitor()
        assert mon.get_quality() == LocalizationQuality.UNKNOWN


# ── is_localized ─────────────────────────────────────────────────────────────

class TestIsLocalized:
    def test_localized_when_good(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=0.0, y=0.0, yaw=0.0,
                        cov_xx=0.01, cov_yy=0.01, cov_yawyaw=0.01)
        assert mon.is_localized() is True

    def test_localized_when_degraded(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=0.0, y=0.0, yaw=0.0,
                        cov_xx=0.05, cov_yy=0.05, cov_yawyaw=0.05)
        # DEGRADED counts as localized (can still navigate)
        assert mon.is_localized() is True

    def test_not_localized_when_lost(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=0.0, y=0.0, yaw=0.0,
                        cov_xx=0.15, cov_yy=0.15, cov_yawyaw=0.15)
        assert mon.is_localized() is False

    def test_not_localized_when_unknown(self):
        mon = LocalizationMonitor()
        assert mon.is_localized() is False


# ── update_pose_simple ────────────────────────────────────────────────────────

class TestUpdatePoseSimple:
    def test_update_simple_no_covariance(self):
        mon = LocalizationMonitor()
        mon.update_pose_simple(x=2.5, y=3.5, yaw=1.0)
        pe = mon.get_pose()
        assert pe is not None
        assert pe.x == pytest.approx(2.5)
        assert pe.y == pytest.approx(3.5)
        assert pe.yaw == pytest.approx(1.0)

    def test_update_simple_does_not_override_quality(self):
        """Simple update without covariance doesn't change quality from UNKNOWN."""
        mon = LocalizationMonitor()
        mon.update_pose_simple(x=1.0, y=1.0, yaw=0.0)
        # No covariance → quality stays UNKNOWN
        assert mon.get_quality() == LocalizationQuality.UNKNOWN


# ── Localization report ───────────────────────────────────────────────────────

class TestLocalizationReport:
    def test_report_fields(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        mon.update_pose(x=1.0, y=2.0, yaw=0.5,
                        cov_xx=0.01, cov_yy=0.01, cov_yawyaw=0.01)
        report = mon.get_report()
        assert isinstance(report, LocalizationReport)
        assert report.quality == LocalizationQuality.GOOD
        assert report.pose is not None
        assert report.covariance_trace == pytest.approx(0.03)

    def test_report_before_update(self):
        mon = LocalizationMonitor()
        report = mon.get_report()
        assert report.quality == LocalizationQuality.UNKNOWN
        assert report.pose is None


# ── Consecutive lost count ────────────────────────────────────────────────────

class TestConsecutiveLostCount:
    def test_consecutive_lost_increments(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        for _ in range(3):
            mon.update_pose(x=0.0, y=0.0, yaw=0.0,
                            cov_xx=0.20, cov_yy=0.20, cov_yawyaw=0.20)
        assert mon.consecutive_lost_count() >= 3

    def test_consecutive_lost_resets_on_good_pose(self):
        mon = LocalizationMonitor(good_cov_threshold=0.05, lost_cov_threshold=0.20)
        for _ in range(3):
            mon.update_pose(x=0.0, y=0.0, yaw=0.0,
                            cov_xx=0.20, cov_yy=0.20, cov_yawyaw=0.20)
        # Good pose resets count
        mon.update_pose(x=1.0, y=1.0, yaw=0.0,
                        cov_xx=0.01, cov_yy=0.01, cov_yawyaw=0.01)
        assert mon.consecutive_lost_count() == 0


# ── Relocalization recording ──────────────────────────────────────────────────

class TestRelocalization:
    def test_relocalization_count_increments(self):
        mon = LocalizationMonitor()
        mon.record_relocalization()
        mon.record_relocalization()
        assert mon.relocalization_count == 2

    def test_relocalization_timestamp_updated(self):
        mon = LocalizationMonitor()
        assert mon.relocalization_count == 0
        mon.record_relocalization()
        assert mon.relocalization_count == 1
