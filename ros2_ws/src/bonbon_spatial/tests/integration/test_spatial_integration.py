"""Integration tests for the bonbon_spatial reasoning pipeline.

Exercise the core modules the SpatialReasoningNode wires together —
EntityTracker, SemanticZoneManager, RestrictedZoneMonitor, BlockageDetector,
DynamicObstaclePredictor, PersonalSpaceEstimator and SocialNavigationHints —
end-to-end, without requiring rclpy. Verifies that a realistic person track
produces consistent zone alerts, blockage state, collision risk and social
hints.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_spatial.core.blockage_detector import BlockageDetector
from bonbon_spatial.core.dynamic_obstacle_predictor import DynamicObstaclePredictor
from bonbon_spatial.core.personal_space_estimator import PersonalSpaceEstimator
from bonbon_spatial.core.restricted_zone_monitor import RestrictedZoneMonitor
from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager
from bonbon_spatial.core.social_navigation_hints import SocialNavigationHints


@dataclass
class _Entity:
    entity_id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    entity_type: str = "person"
    person_id: str = ""
    person_category: str = "adult"
    is_approaching_robot: bool = False
    is_moving_away: bool = False
    approach_speed_mps: float = 0.0

    @property
    def distance_to_robot(self) -> float:
        return (self.x ** 2 + self.y ** 2) ** 0.5


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestSpatialPipelineConsistency:
    def test_person_approaching_through_restricted_zone(self):
        # Restricted zone directly in front of the robot.
        zones = SemanticZoneManager()
        zones.add_zone(
            SemanticZone(
                "no_go", "restricted",
                polygon=[(1.0, -1.0), (3.0, -1.0), (3.0, 1.0), (1.0, 1.0)],
            )
        )
        monitor = RestrictedZoneMonitor(zones)
        predictor = DynamicObstaclePredictor(horizon_sec=3.0)
        estimator = PersonalSpaceEstimator()

        # Person at (2,0) walking straight at the robot.
        person = _Entity("p1", 2.0, 0.0, vx=-1.0, person_id="bob")

        # Zone monitor: should fire an entry alert (person is in no_go).
        alerts = monitor.update([person])
        assert any(a.alert_type == "entry" and a.zone_id == "no_go" for a in alerts)

        # Predictor: head-on approach → high collision risk.
        pred = predictor.predict(person)
        assert pred.risk_level == "high"
        assert pred.is_converging

        # Personal space: 2 m is within the social band.
        space = estimator.estimate(person.distance_to_robot, person.person_category)
        assert space.zone_name in ("social", "personal")

    def test_doorway_blockage_then_clear(self):
        clock = _Clock()
        det = BlockageDetector(persistence_sec=1.0, clock=clock)
        blocker = _Entity("p1", 1.0, 0.0)

        det.update([blocker])
        clock.t = 1.5
        state = det.update([blocker])
        assert state.is_blocked

        # Person steps aside.
        clear = det.update([_Entity("p1", 1.0, 2.0)])
        assert clear.is_blocked is False

    def test_social_hint_matches_proximity(self):
        estimator = PersonalSpaceEstimator()
        hints = SocialNavigationHints(estimator=estimator)
        # Very close person → expect a stop/slow hint.
        close = _Entity("p1", 0.4, 0.0)
        summaries = hints.evaluate_all([close])
        critical = hints.most_critical(summaries)
        assert critical is not None
        assert critical.hint_type in ("stop", "slow_down", "maintain_distance", "keep_distance")

    def test_no_entities_no_alerts(self):
        zones = SemanticZoneManager()
        monitor = RestrictedZoneMonitor(zones)
        predictor = DynamicObstaclePredictor()
        assert monitor.update([]) == []
        assert predictor.most_critical(predictor.predict_all([])) is None
