"""Unit tests for bonbon_actuation.core.proximity_governor.ProximityGovernor."""

from __future__ import annotations

from bonbon_actuation.core.proximity_governor import (
    CAUTION_DISTANCE_M,
    SLOW_DISTANCE_M,
    STOP_DISTANCE_M,
    ProximityGovernor,
)


class TestDefaultClear:
    def test_no_person_full_speed(self):
        gov = ProximityGovernor()
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale == 1.0
        assert d.block_large_motion is False

    def test_emergency_priority_bypasses_derate(self):
        gov = ProximityGovernor()
        gov.update_proximity(0.2, "child")  # very close child
        d = gov.evaluate(requested_priority=20)
        assert d.speed_scale == 1.0
        assert d.block_large_motion is False


class TestProximityBands:
    def test_inside_stop_band_blocks_motion(self):
        gov = ProximityGovernor()
        gov.update_proximity(STOP_DISTANCE_M - 0.05, "adult")
        d = gov.evaluate(requested_priority=5)
        assert d.block_large_motion is True
        assert d.speed_scale <= 0.25

    def test_slow_band_derates(self):
        gov = ProximityGovernor()
        gov.update_proximity((STOP_DISTANCE_M + SLOW_DISTANCE_M) / 2, "adult")
        d = gov.evaluate(requested_priority=5)
        assert d.block_large_motion is False
        assert d.speed_scale <= 0.4

    def test_caution_band_mild_derate(self):
        gov = ProximityGovernor()
        gov.update_proximity((SLOW_DISTANCE_M + CAUTION_DISTANCE_M) / 2, "adult")
        d = gov.evaluate(requested_priority=5)
        assert 0.4 < d.speed_scale <= 0.7

    def test_far_person_full_speed(self):
        gov = ProximityGovernor()
        gov.update_proximity(CAUTION_DISTANCE_M + 1.0, "adult")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale == 1.0


class TestOperatingModes:
    def test_child_safe_caps_speed(self):
        gov = ProximityGovernor()
        gov.set_operating_mode("child_safe")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale <= 0.55

    def test_elderly_caps_speed(self):
        gov = ProximityGovernor()
        gov.set_operating_mode("elderly")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale <= 0.7

    def test_normal_mode_no_cap(self):
        gov = ProximityGovernor()
        gov.set_operating_mode("normal")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale == 1.0


class TestVulnerableCategory:
    def test_child_larger_stop_band(self):
        gov = ProximityGovernor()
        # Distance that is safe for an adult but not for a child.
        gov.update_proximity(STOP_DISTANCE_M + 0.05, "child")
        d = gov.evaluate(requested_priority=5)
        assert d.block_large_motion is True

    def test_adult_at_same_distance_not_blocked(self):
        gov = ProximityGovernor()
        gov.update_proximity(STOP_DISTANCE_M + 0.05, "adult")
        d = gov.evaluate(requested_priority=5)
        assert d.block_large_motion is False


class TestSpatialHints:
    def test_stop_hint_blocks(self):
        gov = ProximityGovernor()
        gov.update_hint("stop")
        d = gov.evaluate(requested_priority=5)
        assert d.block_large_motion is True

    def test_slow_down_hint_derates(self):
        gov = ProximityGovernor()
        gov.update_hint("slow_down")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale <= 0.5

    def test_clear_proximity_releases(self):
        gov = ProximityGovernor()
        gov.update_proximity(0.2, "child")
        gov.update_hint("stop")
        gov.clear_proximity()
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale == 1.0
        assert d.block_large_motion is False


class TestSpeedFloor:
    def test_speed_never_below_floor(self):
        gov = ProximityGovernor()
        gov.set_operating_mode("child_safe")
        gov.update_proximity(0.1, "child")
        gov.update_hint("stop")
        d = gov.evaluate(requested_priority=5)
        assert d.speed_scale >= 0.1
