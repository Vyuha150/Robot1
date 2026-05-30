"""Unit tests for bonbon_spatial.core.dynamic_obstacle_predictor."""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_spatial.core.dynamic_obstacle_predictor import (
    COLLISION_DISTANCE_M,
    DynamicObstaclePredictor,
)


@dataclass
class _E:
    entity_id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    entity_type: str = "person"


class TestPrediction:
    def test_stationary_entity_no_convergence(self):
        pred = DynamicObstaclePredictor()
        p = pred.predict(_E("a", 2.0, 0.0, 0.0, 0.0))
        assert p.is_converging is False
        assert abs(p.closest_distance_m - 2.0) < 1e-3
        assert p.risk_level in ("none", "low")

    def test_head_on_approach_is_high_risk(self):
        pred = DynamicObstaclePredictor(horizon_sec=3.0)
        # Person 2 m ahead, walking straight at robot at 1 m/s.
        p = pred.predict(_E("a", 2.0, 0.0, -1.0, 0.0))
        assert p.is_converging is True
        assert p.closest_distance_m <= COLLISION_DISTANCE_M
        assert p.risk_level == "high"

    def test_crossing_path_near_miss_medium(self):
        pred = DynamicObstaclePredictor(horizon_sec=3.0)
        # Person ahead and to the side, crossing laterally — comes within ~0.8 m.
        p = pred.predict(_E("a", 1.5, 0.8, -0.5, 0.0))
        assert p.is_converging is True
        assert p.risk_level in ("medium", "high")

    def test_diverging_entity_low_or_none(self):
        pred = DynamicObstaclePredictor()
        # Person 2 m away moving further away.
        p = pred.predict(_E("a", 2.0, 0.0, 1.0, 0.0))
        assert p.is_converging is False
        assert p.risk_level in ("none", "low")

    def test_predicted_path_sampled(self):
        pred = DynamicObstaclePredictor(horizon_sec=1.0, timestep_sec=0.25)
        p = pred.predict(_E("a", 2.0, 0.0, -1.0, 0.0))
        assert len(p.predicted_path) == 4  # 1.0 / 0.25
        # Each path point is (t, x, y).
        assert all(len(pt) == 3 for pt in p.predicted_path)


class TestPredictAllOrdering:
    def test_highest_risk_first(self):
        pred = DynamicObstaclePredictor(horizon_sec=3.0)
        entities = [
            _E("far", 5.0, 0.0, 0.0, 0.0),          # none
            _E("approach", 2.0, 0.0, -1.0, 0.0),    # high
            _E("cross", 1.5, 0.8, -0.4, 0.0),       # medium
        ]
        preds = pred.predict_all(entities)
        assert preds[0].entity_id == "approach"
        crit = pred.most_critical(preds)
        assert crit.entity_id == "approach"

    def test_most_critical_empty_is_none(self):
        pred = DynamicObstaclePredictor()
        assert pred.most_critical([]) is None
