"""Tests for bonbon_spatial.core.entity_tracker."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from bonbon_spatial.core.entity_tracker import EntityTracker, TrackedEntity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_person(tracking_id: int, x: float, y: float,
                 vx: float = 0.0, vy: float = 0.0,
                 person_id: str = "") -> MagicMock:
    """Build a minimal PersonState mock compatible with EntityTracker.update_person."""
    ps = MagicMock()
    ps.tracking_id = tracking_id
    ps.person_id = person_id or f"p{tracking_id}"
    ps.pose.pose.position.x = x
    ps.pose.pose.position.y = y
    ps.pose.pose.position.z = 0.0
    ps.velocity.x = vx
    ps.velocity.y = vy
    ps.velocity.z = 0.0
    return ps


# ---------------------------------------------------------------------------
# Creation & update
# ---------------------------------------------------------------------------

class TestEntityTrackerCreation:
    def test_new_entity_created_on_update(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(1, 2.0, 1.5))
        assert entity.entity_id == "person_1"
        assert entity.tracking_id == 1
        assert entity.entity_type == "person"

    def test_position_stored_correctly(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(1, 3.0, 4.0))
        assert abs(entity.x - 3.0) < 1e-6
        assert abs(entity.y - 4.0) < 1e-6

    def test_person_id_stored(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(5, 1.0, 0.0, person_id="alice"))
        assert entity.person_id == "alice"

    def test_count_increments_for_new_entities(self):
        tracker = EntityTracker()
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        tracker.update_person(_mock_person(2, 2.0, 0.0))
        tracker.update_person(_mock_person(3, 3.0, 0.0))
        assert tracker.count() == 3

    def test_update_existing_entity_does_not_grow_count(self):
        tracker = EntityTracker()
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        tracker.update_person(_mock_person(1, 2.0, 0.0))
        assert tracker.count() == 1

    def test_update_replaces_position(self):
        tracker = EntityTracker()
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        tracker.update_person(_mock_person(1, 9.0, 0.0))
        entity = tracker.get_by_tracking_id(1)
        assert abs(entity.x - 9.0) < 1e-6


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestEntityTrackerLookup:
    def test_get_by_tracking_id(self):
        tracker = EntityTracker()
        tracker.update_person(_mock_person(7, 1.0, 0.0))
        entity = tracker.get_by_tracking_id(7)
        assert entity is not None
        assert entity.tracking_id == 7

    def test_get_by_tracking_id_not_found(self):
        tracker = EntityTracker()
        assert tracker.get_by_tracking_id(99) is None

    def test_get_by_id(self):
        tracker = EntityTracker()
        tracker.update_person(_mock_person(3, 1.0, 0.0))
        entity = tracker.get_by_id("person_3")
        assert entity is not None

    def test_get_by_id_not_found(self):
        tracker = EntityTracker()
        assert tracker.get_by_id("person_999") is None

    def test_get_all_returns_all_entities(self):
        tracker = EntityTracker()
        for i in range(5):
            tracker.update_person(_mock_person(i, float(i), 0.0))
        entities = tracker.get_all()
        assert len(entities) == 5


# ---------------------------------------------------------------------------
# Staleness cleanup
# ---------------------------------------------------------------------------

class TestEntityTrackerCleanup:
    def test_stale_entity_removed(self):
        tracker = EntityTracker(timeout_sec=0.05)
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        time.sleep(0.10)
        removed = tracker.cleanup_stale()
        assert "person_1" in removed
        assert tracker.count() == 0

    def test_fresh_entity_not_removed(self):
        tracker = EntityTracker(timeout_sec=10.0)
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        removed = tracker.cleanup_stale()
        assert len(removed) == 0
        assert tracker.count() == 1

    def test_mixed_stale_and_fresh(self):
        tracker = EntityTracker(timeout_sec=0.05)
        tracker.update_person(_mock_person(1, 1.0, 0.0))
        time.sleep(0.10)
        tracker.update_person(_mock_person(2, 2.0, 0.0))  # fresh
        removed = tracker.cleanup_stale()
        assert "person_1" in removed
        assert "person_2" not in removed
        assert tracker.count() == 1


# ---------------------------------------------------------------------------
# Approach flag computation
# ---------------------------------------------------------------------------

class TestEntityTrackerApproachFlags:
    def test_approaching_robot_when_velocity_points_toward_origin(self):
        tracker = EntityTracker()
        # Person at (3, 0) moving toward origin at -0.5 m/s in x
        entity = tracker.update_person(_mock_person(1, 3.0, 0.0, vx=-0.5))
        assert entity.is_approaching_robot is True
        assert entity.approach_speed_mps > 0.1

    def test_moving_away_when_velocity_points_away_from_origin(self):
        tracker = EntityTracker()
        # Person at (3, 0) moving away at +0.5 m/s in x
        entity = tracker.update_person(_mock_person(1, 3.0, 0.0, vx=0.5))
        assert entity.is_moving_away is True

    def test_stationary_person_neither_approaching_nor_retreating(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(1, 3.0, 0.0, vx=0.0))
        assert entity.is_approaching_robot is False
        assert entity.is_moving_away is False


# ---------------------------------------------------------------------------
# Distance to robot
# ---------------------------------------------------------------------------

class TestEntityTrackerDistance:
    def test_pythagorean_distance(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(1, 3.0, 4.0))
        assert abs(entity.distance_to_robot - 5.0) < 0.01

    def test_entity_at_origin(self):
        tracker = EntityTracker()
        entity = tracker.update_person(_mock_person(1, 0.0, 0.0))
        assert abs(entity.distance_to_robot) < 1e-6
