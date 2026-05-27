from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Iterable, List, Tuple


Point = Tuple[float, float]


@dataclass
class DynamicObstacle:
    name: str
    kind: str
    position: Point
    velocity: Point = (0.0, 0.0)
    radius_m: float = 0.35
    active: bool = True

    def step(self, dt: float) -> None:
        if self.active:
            self.position = (
                self.position[0] + self.velocity[0] * dt,
                self.position[1] + self.velocity[1] * dt,
            )


class DynamicObstacleController:
    def __init__(self, obstacles: Iterable[DynamicObstacle] | None = None) -> None:
        self.obstacles: List[DynamicObstacle] = list(obstacles or [])

    def add(self, obstacle: DynamicObstacle) -> None:
        self.obstacles.append(obstacle)

    def step(self, dt: float) -> None:
        for obstacle in self.obstacles:
            obstacle.step(dt)

    def nearest_distance(self, point: Point) -> float:
        active = [o for o in self.obstacles if o.active]
        if not active:
            return float("inf")
        return min(hypot(point[0] - o.position[0], point[1] - o.position[1]) - o.radius_m for o in active)

    def blocks_path(self, point: Point, clearance_m: float) -> bool:
        return self.nearest_distance(point) < clearance_m
