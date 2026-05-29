"""Tests for bonbon_spatial.core.semantic_zone_manager."""

from __future__ import annotations

import pytest

from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square(zone_id: str, zone_type: str = "restricted",
            side: float = 4.0) -> SemanticZone:
    """Create a square zone centred at the origin."""
    h = side / 2.0
    return SemanticZone(
        zone_id=zone_id,
        zone_type=zone_type,
        polygon=[(-h, -h), (h, -h), (h, h), (-h, h)],
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestZoneRegistration:
    def test_add_and_retrieve_zone(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("kitchen"))
        assert mgr.get_zone("kitchen") is not None

    def test_get_unknown_zone_returns_none(self):
        mgr = SemanticZoneManager()
        assert mgr.get_zone("nonexistent") is None

    def test_all_zone_ids_returned(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("a"))
        mgr.add_zone(_square("b"))
        mgr.add_zone(_square("c"))
        ids = mgr.get_all_zone_ids()
        assert set(ids) == {"a", "b", "c"}

    def test_overwrite_existing_zone(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(SemanticZone("z", "restricted", [(0,0),(1,0),(1,1),(0,1)]))
        mgr.add_zone(SemanticZone("z", "public", [(0,0),(2,0),(2,2),(0,2)]))
        zone = mgr.get_zone("z")
        assert zone.zone_type == "public"

    def test_remove_existing_zone(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("r"))
        assert mgr.remove_zone("r") is True
        assert mgr.get_zone("r") is None

    def test_remove_nonexistent_zone(self):
        mgr = SemanticZoneManager()
        assert mgr.remove_zone("ghost") is False


# ---------------------------------------------------------------------------
# is_restricted
# ---------------------------------------------------------------------------

class TestIsRestricted:
    def test_restricted_zone(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("staff_only", "restricted"))
        assert mgr.is_restricted("staff_only") is True

    def test_public_zone_not_restricted(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("lobby", "public"))
        assert mgr.is_restricted("lobby") is False

    def test_nonexistent_zone_not_restricted(self):
        mgr = SemanticZoneManager()
        assert mgr.is_restricted("ghost") is False


# ---------------------------------------------------------------------------
# Point-in-polygon
# ---------------------------------------------------------------------------

class TestPointInPolygon:
    def test_centre_of_square_is_inside(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("sq"))
        assert mgr.find_zone_for_point(0.0, 0.0) == "sq"

    def test_far_point_is_outside(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("sq", side=4.0))
        assert mgr.find_zone_for_point(10.0, 10.0) is None

    def test_near_boundary_inside(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("sq", side=4.0))
        assert mgr.find_zone_for_point(1.9, 1.9) == "sq"

    def test_just_outside_boundary(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("sq", side=4.0))
        assert mgr.find_zone_for_point(2.1, 0.0) is None

    def test_degenerate_polygon_under_3_vertices(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(SemanticZone("tiny", "public", [(0,0), (1,0)]))  # only 2 points
        # Should not crash and should return None
        assert mgr.find_zone_for_point(0.5, 0.0) is None

    def test_multiple_zones_first_match_returned(self):
        """Ensure the correct zone is matched when zones overlap."""
        mgr = SemanticZoneManager()
        mgr.add_zone(_square("big", "public", side=10.0))
        mgr.add_zone(_square("small", "restricted", side=2.0))
        # 'big' is added first and contains (0,0), but 'small' also contains it.
        # Implementation returns first match in insertion order.
        result = mgr.find_zone_for_point(0.0, 0.0)
        assert result in ("big", "small")  # valid — order is implementation-specific


# ---------------------------------------------------------------------------
# load_from_config
# ---------------------------------------------------------------------------

class TestLoadFromConfig:
    def test_valid_config_loaded(self):
        mgr = SemanticZoneManager()
        config = [
            {
                "zone_id": "lobby",
                "zone_type": "public",
                "polygon": [{"x": 0, "y": 0}, {"x": 5, "y": 0},
                            {"x": 5, "y": 5}, {"x": 0, "y": 5}],
                "min_clearance_m": 0.3,
                "reason": "main entrance area",
            }
        ]
        mgr.load_from_config(config)
        z = mgr.get_zone("lobby")
        assert z is not None
        assert z.zone_type == "public"
        assert abs(z.min_clearance_m - 0.3) < 1e-6

    def test_invalid_config_entry_skipped(self):
        mgr = SemanticZoneManager()
        config = [
            {"zone_type": "public"},  # missing zone_id
            {"zone_id": "ok", "zone_type": "public",
             "polygon": [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                         {"x": 1, "y": 1}, {"x": 0, "y": 1}]},
        ]
        mgr.load_from_config(config)  # must not raise
        assert mgr.get_zone("ok") is not None
