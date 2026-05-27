from __future__ import annotations

from bonbon_simulation.simulators.dynamic_obstacle import DynamicObstacle


class PedestrianSimulator:
    """Factory for repeatable human actor profiles used in scenario configs."""

    @staticmethod
    def slow_elderly(name: str, x: float, y: float) -> DynamicObstacle:
        return DynamicObstacle(name=name, kind="slow_elderly_pedestrian", position=(x, y), velocity=(0.25, 0.0), radius_m=0.38)

    @staticmethod
    def child_running(name: str, x: float, y: float) -> DynamicObstacle:
        return DynamicObstacle(name=name, kind="child_running", position=(x, y), velocity=(0.0, -2.2), radius_m=0.28)

    @staticmethod
    def blocking_person(name: str, x: float, y: float) -> DynamicObstacle:
        return DynamicObstacle(name=name, kind="person_blocking_path", position=(x, y), velocity=(0.0, 0.0), radius_m=0.45)

    @staticmethod
    def wheelchair_user(name: str, x: float, y: float) -> DynamicObstacle:
        return DynamicObstacle(name=name, kind="wheelchair_user", position=(x, y), velocity=(0.35, 0.0), radius_m=0.55)

    @staticmethod
    def moving_cart(name: str, x: float, y: float) -> DynamicObstacle:
        return DynamicObstacle(name=name, kind="moving_cart", position=(x, y), velocity=(0.0, 0.65), radius_m=0.50)
