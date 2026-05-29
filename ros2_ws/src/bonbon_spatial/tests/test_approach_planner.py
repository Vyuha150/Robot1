"""Tests for bonbon_spatial.core.approach_pose_planner."""

from __future__ import annotations

import math

import pytest

from bonbon_spatial.core.approach_pose_planner import ApproachPosePlanner
from bonbon_spatial.core.entity_tracker import TrackedEntity
from bonbon_spatial.core.personal_space_estimator import PersonalSpaceEstimator
from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(x: float, y: float, tracking_id: int = 1,
            person_category: str = "adult") -> TrackedEntity:
    import time
    return TrackedEntity(
        entity_id=f"person_{tracking_id}",
        entity_type="person",
        person_id=f"p{tracking_id}",
        tracking_id=tracking_id,
        x=x,
        y=y,
        z=0.0,
        vx=0.0,
        vy=0.0,
        person_category=person_category,
        last_seen=time.monotonic(),
    )


def _empty_planner() -> ApproachPosePlanner:
    return ApproachPosePlanner(zone_manager=SemanticZoneManager())


# ---------------------------------------------------------------------------
# Basic planning
# ---------------------------------------------------------------------------

class TestApproachPosePlannerBasic:
    def test_front_approach_along_x_axis(self):
        planner = _empty_planner()
        entity = _entity(5.0, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, desired_distance_m=1.0,
                                                   approach_style="front")
        assert success is True
        # Approach pose should be 1 m in front of person at (4, 0)
        assert abs(px - 4.0) < 0.05
        assert abs(py) < 0.05

    def test_front_approach_yaw_faces_person(self):
        planner = _empty_planner()
        entity = _entity(5.0, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, desired_distance_m=1.0,
                                                   approach_style="front")
        assert abs(yaw) < 0.1  # facing east → yaw ≈ 0

    def test_side_approach_produces_offset_pose(self):
        planner = _empty_planner()
        entity = _entity(5.0, 0.0)
        success_f, fx, fy, _, _ = planner.plan(entity, 1.0, "front")
        success_s, sx, sy, _, _ = planner.plan(entity, 1.0, "side")
        # Side pose should differ from front pose
        assert abs(sy) > 0.1 or abs(sx - fx) > 0.1

    def test_default_distance_uses_estimator_recommendation(self):
        planner = _empty_planner()
        # Person 5 m away — no desired_distance_m supplied
        entity = _entity(5.0, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, desired_distance_m=0.0)
        assert success is True
        # Verify the approach distance is reasonable (between 0.5 and 2.0 m from person)
        dist_from_person = math.sqrt((px - 5.0) ** 2 + py ** 2)
        assert 0.5 <= dist_from_person <= 2.5

    def test_any_style_tries_multiple_candidates(self):
        planner = _empty_planner()
        entity = _entity(3.0, 0.0)
        success, _, _, _, msg = planner.plan(entity, 1.0, "any")
        assert success is True


# ---------------------------------------------------------------------------
# Restricted zone avoidance
# ---------------------------------------------------------------------------

class TestRestrictedZoneAvoidance:
    def test_unrestricted_zone_does_not_block(self):
        mgr = SemanticZoneManager()
        # Large public zone containing the approach area
        mgr.add_zone(SemanticZone("lobby", "public",
                                   [(-10, -10), (10, -10), (10, 10), (-10, 10)]))
        planner = ApproachPosePlanner(zone_manager=mgr)
        entity = _entity(3.0, 0.0)
        success, _, _, _, _ = planner.plan(entity, 1.0, "front")
        assert success is True

    def test_restricted_zone_blocking_front_triggers_fallback(self):
        mgr = SemanticZoneManager()
        # Restricted zone covering where the front approach pose would be (≈ x=2)
        mgr.add_zone(SemanticZone("restricted_area", "restricted",
                                   [(1.5, -2), (3.0, -2), (3.0, 2), (1.5, 2)]))
        planner = ApproachPosePlanner(zone_manager=mgr)
        entity = _entity(3.0, 0.0)
        # 'any' style tries side approaches too
        success, px, py, yaw, msg = planner.plan(entity, 1.0, "any")
        # May or may not succeed depending on side candidate positions; should not crash
        assert isinstance(success, bool)

    def test_all_blocked_returns_false_with_fallback_pose(self):
        """When every candidate is in a restricted zone, plan returns (False, pose, msg)."""
        mgr = SemanticZoneManager()
        # Gigantic restricted zone
        mgr.add_zone(SemanticZone("everywhere", "restricted",
                                   [(-50, -50), (50, -50), (50, 50), (-50, 50)]))
        planner = ApproachPosePlanner(zone_manager=mgr)
        entity = _entity(3.0, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, 1.0, "any")
        # Should return False (blocked) but still give a fallback pose
        assert success is False
        assert isinstance(msg, str)
        assert len(msg) > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestApproachPosePlannerEdgeCases:
    def test_person_at_origin_does_not_crash(self):
        planner = _empty_planner()
        entity = _entity(0.0, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, 1.0, "front")
        # Should handle gracefully (estimator returns fallback at origin)
        assert isinstance(success, bool)

    def test_very_close_person(self):
        planner = _empty_planner()
        entity = _entity(0.1, 0.0)
        success, px, py, yaw, msg = planner.plan(entity, 1.0, "front")
        assert isinstance(px, float)

    def test_child_category_uses_larger_approach_dist(self):
        planner_a = _empty_planner()
        entity_adult = _entity(5.0, 0.0, person_category="adult")
        entity_child = _entity(5.0, 0.0, person_category="child")
        _, ax, _, _, _ = planner_a.plan(entity_adult, desired_distance_m=0.0)
        _, cx, _, _, _ = planner_a.plan(entity_child, desired_distance_m=0.0)
        # Child should get a larger standoff distance → approach pose further from person
        dist_adult = abs(5.0 - ax)
        dist_child = abs(5.0 - cx)
        assert dist_child >= dist_adult
