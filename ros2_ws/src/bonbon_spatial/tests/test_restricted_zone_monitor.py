"""Unit tests for bonbon_spatial.core.restricted_zone_monitor."""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_spatial.core.restricted_zone_monitor import RestrictedZoneMonitor
from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager


@dataclass
class _E:
    entity_id: str
    x: float
    y: float
    entity_type: str = "person"
    person_id: str = ""


def _mgr_with_restricted_box() -> SemanticZoneManager:
    mgr = SemanticZoneManager()
    # Restricted square covering (1..3, -1..1).
    mgr.add_zone(
        SemanticZone(
            zone_id="staff_only",
            zone_type="restricted",
            polygon=[(1.0, -1.0), (3.0, -1.0), (3.0, 1.0), (1.0, 1.0)],
        )
    )
    return mgr


class TestEntryExitEdges:
    def test_entry_alert_on_first_entry(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        alerts = mon.update([_E("p1", 2.0, 0.0, person_id="alice")])
        assert len(alerts) == 1
        assert alerts[0].alert_type == "entry"
        assert alerts[0].zone_id == "staff_only"
        assert alerts[0].person_id == "alice"

    def test_no_duplicate_entry_while_inside(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        mon.update([_E("p1", 2.0, 0.0)])
        alerts = mon.update([_E("p1", 2.1, 0.1)])  # still inside
        assert alerts == []

    def test_exit_alert_when_leaving(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        mon.update([_E("p1", 2.0, 0.0)])
        alerts = mon.update([_E("p1", 5.0, 0.0)])  # left the zone
        assert len(alerts) == 1
        assert alerts[0].alert_type == "exit"

    def test_exit_alert_when_entity_disappears(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        mon.update([_E("p1", 2.0, 0.0)])
        alerts = mon.update([])  # entity track lost while inside
        assert len(alerts) == 1
        assert alerts[0].alert_type == "exit"

    def test_entity_outside_never_alerts(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        alerts = mon.update([_E("p1", 5.0, 5.0)])
        assert alerts == []


class TestNonRestrictedZones:
    def test_public_zone_does_not_alert(self):
        mgr = SemanticZoneManager()
        mgr.add_zone(
            SemanticZone(
                zone_id="lobby",
                zone_type="public",
                polygon=[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],
            )
        )
        mon = RestrictedZoneMonitor(mgr)
        alerts = mon.update([_E("p1", 2.0, 2.0)])
        assert alerts == []


class TestOccupancyTracking:
    def test_occupants_map(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        mon.update([_E("p1", 2.0, 0.0)])
        assert mon.occupants() == {"p1": "staff_only"}

    def test_reset_clears_occupants(self):
        mon = RestrictedZoneMonitor(_mgr_with_restricted_box())
        mon.update([_E("p1", 2.0, 0.0)])
        mon.reset()
        assert mon.occupants() == {}
