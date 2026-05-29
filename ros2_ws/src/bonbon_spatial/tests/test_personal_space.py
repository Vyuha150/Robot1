"""Tests for bonbon_spatial.core.personal_space_estimator."""

from __future__ import annotations

import math

import pytest

from bonbon_spatial.core.personal_space_estimator import (
    PersonalSpaceEstimator,
    ProxemicZones,
    SpaceEstimate,
)


# ---------------------------------------------------------------------------
# Zone classification
# ---------------------------------------------------------------------------

class TestZoneClassification:
    def setup_method(self):
        self.est = PersonalSpaceEstimator()

    def test_intimate_zone(self):
        result = self.est.estimate(0.3)
        assert result.zone_name == "intimate"

    def test_personal_zone(self):
        result = self.est.estimate(0.9)
        assert result.zone_name == "personal"

    def test_social_zone(self):
        result = self.est.estimate(2.0)
        assert result.zone_name == "social"

    def test_public_zone(self):
        result = self.est.estimate(5.0)
        assert result.zone_name == "public"

    def test_distant_zone(self):
        result = self.est.estimate(10.0)
        assert result.zone_name == "distant"

    def test_result_carries_input_distance(self):
        result = self.est.estimate(2.5)
        assert abs(result.distance_m - 2.5) < 1e-6


# ---------------------------------------------------------------------------
# Navigation hints
# ---------------------------------------------------------------------------

class TestNavigationHints:
    def setup_method(self):
        self.est = PersonalSpaceEstimator()

    def test_stop_hint_when_too_close(self):
        # stop_distance_m default = 0.6
        result = self.est.estimate(0.4)
        assert result.hint_type == "stop"
        assert result.is_too_close is True

    def test_slow_down_hint_in_slow_zone(self):
        # slow_distance_m = 1.5; between 0.6 and 1.5
        result = self.est.estimate(1.1)
        assert result.hint_type == "slow_down"
        assert result.should_slow is True
        assert result.is_too_close is False

    def test_keep_distance_in_social_zone(self):
        # social zone start = 1.2; beyond slow threshold (1.5)
        result = self.est.estimate(2.0)
        assert result.hint_type == "keep_distance"

    def test_approach_allowed_beyond_social(self):
        result = self.est.estimate(5.0)
        assert result.hint_type == "approach_allowed"


# ---------------------------------------------------------------------------
# Vulnerable category multiplier
# ---------------------------------------------------------------------------

class TestVulnerableCategoryMultiplier:
    def setup_method(self):
        self.est = PersonalSpaceEstimator()

    def test_child_triggers_stop_at_larger_distance(self):
        # Adult stop = 0.6 m; child stop = 0.6 * 1.3 = 0.78 m
        adult = self.est.estimate(0.7, person_category="adult")
        child = self.est.estimate(0.7, person_category="child")
        # Adult at 0.7 should NOT be stopped; child should be
        assert adult.is_too_close is False
        assert child.is_too_close is True

    def test_elderly_same_as_child_multiplier(self):
        child_result = self.est.estimate(0.7, person_category="child")
        elderly_result = self.est.estimate(0.7, person_category="elderly")
        assert child_result.hint_type == elderly_result.hint_type

    def test_wheelchair_triggers_stop_at_larger_distance(self):
        adult = self.est.estimate(0.7, person_category="adult")
        wheelchair = self.est.estimate(0.7, person_category="wheelchair")
        assert adult.hint_type != wheelchair.hint_type or wheelchair.is_too_close

    def test_staff_no_multiplier(self):
        adult = self.est.estimate(0.7, person_category="adult")
        staff = self.est.estimate(0.7, person_category="staff")
        assert adult.hint_type == staff.hint_type

    def test_unknown_no_multiplier(self):
        adult = self.est.estimate(0.7, person_category="adult")
        unknown = self.est.estimate(0.7, person_category="unknown")
        assert adult.hint_type == unknown.hint_type


# ---------------------------------------------------------------------------
# Custom zones
# ---------------------------------------------------------------------------

class TestCustomZones:
    def test_custom_stop_distance_respected(self):
        zones = ProxemicZones(stop_distance_m=2.0)
        est = PersonalSpaceEstimator(zones=zones)
        result = est.estimate(1.5)
        assert result.is_too_close is True

    def test_custom_recommended_approach_dist(self):
        zones = ProxemicZones(approach_target_m=0.5)
        est = PersonalSpaceEstimator(zones=zones)
        result = est.estimate(5.0)
        assert abs(result.recommended_approach_dist_m - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Approach pose computation
# ---------------------------------------------------------------------------

class TestComputeApproachPose:
    def setup_method(self):
        self.est = PersonalSpaceEstimator()

    def test_person_along_x_axis(self):
        px, py, yaw = self.est.compute_approach_pose(5.0, 0.0, 1.0)
        assert abs(px - 4.0) < 0.01
        assert abs(py) < 0.01
        assert abs(yaw) < 0.1  # facing person, yaw ≈ 0

    def test_person_along_y_axis(self):
        px, py, yaw = self.est.compute_approach_pose(0.0, 5.0, 1.0)
        assert abs(px) < 0.01
        assert abs(py - 4.0) < 0.01
        assert abs(yaw - math.pi / 2) < 0.1

    def test_person_at_origin_returns_fallback(self):
        px, py, yaw = self.est.compute_approach_pose(0.0, 0.0, 1.0)
        assert px == 0.0 and py == 0.0 and yaw == 0.0

    def test_approach_distance_correct(self):
        # Person at (3, 4) — distance 5; approach at 1 m → pose should be 1 m from person
        px, py, yaw = self.est.compute_approach_pose(3.0, 4.0, 1.0)
        dist_from_person = math.sqrt((px - 3.0) ** 2 + (py - 4.0) ** 2)
        assert abs(dist_from_person - 1.0) < 0.02

    def test_yaw_faces_person(self):
        px, py, yaw = self.est.compute_approach_pose(4.0, 0.0, 1.0)
        # Approach pose at (3, 0); person at (4, 0). Facing east → yaw should be 0
        assert abs(yaw) < 0.1
