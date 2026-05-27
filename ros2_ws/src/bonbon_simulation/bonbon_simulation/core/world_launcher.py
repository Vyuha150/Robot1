from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorldLaunchPlan:
    world_name: str
    world_path: Path
    headless: bool
    use_ignition: bool
    command: tuple[str, ...]


class WorldLauncher:
    """Builds reproducible Gazebo/Ignition launch plans without starting GUI tools."""

    def __init__(self, world_dir: str | Path) -> None:
        self.world_dir = Path(world_dir)

    def plan(
        self, world_name: str, *, headless: bool = True, use_ignition: bool = True
    ) -> WorldLaunchPlan:
        world_path = self.world_dir / f"{world_name}.world"
        if not world_path.exists():
            raise FileNotFoundError(f"World file not found: {world_path}")
        if use_ignition:
            command = (
                "ign",
                "gazebo",
                "-r",
                "-s" if headless else str(world_path),
                str(world_path),
            )
        else:
            command = (
                ("gazebo", "--verbose", str(world_path))
                if not headless
                else ("gzserver", str(world_path))
            )
        return WorldLaunchPlan(world_name, world_path, headless, use_ignition, command)
