"""DynamicObstaclePredictor — short-horizon trajectory & collision-risk forecasting.

Given tracked entities (robot-frame position + velocity), this predicts where
each entity will be over a short horizon using a constant-velocity model, and
estimates the closest predicted approach to the robot. It also estimates
time-to-closest-approach (TTCA) so the behaviour engine / navigation can react
*before* a person walks into the robot's path.

Constant-velocity is deliberately simple: at 5–10 Hz over a 1–3 s horizon it is
robust, cheap, and good enough for social-distance reasoning. It does not try to
model intent — that is the behaviour engine's job.

No ROS2 dependency — pure geometry, fully unit-testable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Protocol

_logger = logging.getLogger(__name__)

# Risk thresholds (metres) on the predicted closest approach.
COLLISION_DISTANCE_M = 0.5    # predicted to come within this → high risk
NEAR_MISS_DISTANCE_M = 1.0    # predicted to come within this → medium risk
DEFAULT_HORIZON_SEC = 2.5
DEFAULT_TIMESTEP_SEC = 0.25


class _EntityLike(Protocol):
    entity_id: str
    entity_type: str
    x: float
    y: float
    vx: float
    vy: float


@dataclass
class ObstaclePrediction:
    """Predicted trajectory summary for one entity."""

    entity_id: str
    closest_distance_m: float       # minimum predicted robot–entity distance
    time_to_closest_sec: float      # when the closest approach occurs
    current_distance_m: float
    is_converging: bool             # getting closer (closest < current)
    risk_level: str                 # 'none' | 'low' | 'medium' | 'high'
    predicted_path: List[tuple]     # [(t, x, y), …] sampled future positions


class DynamicObstaclePredictor:
    """Constant-velocity short-horizon predictor for tracked entities.

    Args:
        horizon_sec: How far ahead to predict.
        timestep_sec: Sampling interval along the predicted path.
    """

    def __init__(
        self,
        horizon_sec: float = DEFAULT_HORIZON_SEC,
        timestep_sec: float = DEFAULT_TIMESTEP_SEC,
    ) -> None:
        self._horizon = max(0.1, horizon_sec)
        self._dt = max(0.05, timestep_sec)

    def predict(self, entity: _EntityLike) -> ObstaclePrediction:
        """Predict one entity's closest approach to the robot (at the origin)."""
        x0, y0 = entity.x, entity.y
        vx, vy = entity.vx, entity.vy
        current_dist = math.hypot(x0, y0)

        closest_dist = current_dist
        t_closest = 0.0
        path: List[tuple] = []

        steps = int(self._horizon / self._dt)
        for i in range(1, steps + 1):
            t = i * self._dt
            xt = x0 + vx * t
            yt = y0 + vy * t
            path.append((round(t, 3), round(xt, 3), round(yt, 3)))
            d = math.hypot(xt, yt)
            if d < closest_dist:
                closest_dist = d
                t_closest = t

        is_converging = closest_dist < current_dist - 1e-3
        risk = self._classify(closest_dist, is_converging)

        return ObstaclePrediction(
            entity_id=entity.entity_id,
            closest_distance_m=round(closest_dist, 3),
            time_to_closest_sec=round(t_closest, 3),
            current_distance_m=round(current_dist, 3),
            is_converging=is_converging,
            risk_level=risk,
            predicted_path=path,
        )

    def predict_all(self, entities: List[_EntityLike]) -> List[ObstaclePrediction]:
        """Predict all entities, ordered by risk (highest first)."""
        preds = [self.predict(e) for e in entities]
        order = {"high": 0, "medium": 1, "low": 2, "none": 3}
        preds.sort(key=lambda p: (order[p.risk_level], p.closest_distance_m))
        return preds

    def most_critical(
        self, predictions: List[ObstaclePrediction]
    ) -> Optional[ObstaclePrediction]:
        """Return the highest-risk prediction, or ``None`` if list is empty."""
        if not predictions:
            return None
        order = {"high": 0, "medium": 1, "low": 2, "none": 3}
        return min(predictions, key=lambda p: (order[p.risk_level], p.closest_distance_m))

    @staticmethod
    def _classify(closest_dist: float, is_converging: bool) -> str:
        """Map predicted closest approach + convergence to a risk level."""
        if closest_dist <= COLLISION_DISTANCE_M and is_converging:
            return "high"
        if closest_dist <= NEAR_MISS_DISTANCE_M and is_converging:
            return "medium"
        if closest_dist <= NEAR_MISS_DISTANCE_M:
            return "low"
        return "none"
