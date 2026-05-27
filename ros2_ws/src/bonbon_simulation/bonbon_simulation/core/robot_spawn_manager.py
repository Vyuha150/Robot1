from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bonbon_simulation.core.config import RobotDimensions


@dataclass(frozen=True)
class SpawnRequest:
    robot_name: str
    pose: tuple[float, float, float]
    urdf_path: Path
    parameters: dict[str, float]


class RobotSpawnManager:
    """Validates robot model assets and prepares Gazebo spawn requests."""

    def __init__(self, urdf_path: str | Path, dimensions: RobotDimensions) -> None:
        self.urdf_path = Path(urdf_path)
        self.dimensions = dimensions

    def create_spawn_request(
        self,
        robot_name: str = "bonbon",
        x: float = 0.0,
        y: float = 0.0,
        yaw: float = 0.0,
    ) -> SpawnRequest:
        if not self.urdf_path.exists():
            raise FileNotFoundError(f"Robot xacro not found: {self.urdf_path}")
        return SpawnRequest(
            robot_name=robot_name,
            pose=(float(x), float(y), float(yaw)),
            urdf_path=self.urdf_path,
            parameters={
                "length_m": self.dimensions.length_m,
                "width_m": self.dimensions.width_m,
                "height_m": self.dimensions.height_m,
                "footprint_radius_m": self.dimensions.footprint_radius_m,
                "wheel_radius_m": self.dimensions.wheel_radius_m,
                "wheel_separation_m": self.dimensions.wheel_separation_m,
            },
        )
