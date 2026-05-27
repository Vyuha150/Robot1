from __future__ import annotations

from pathlib import Path

import pytest
from bonbon_simulation.core.config import SimulationConfig
from bonbon_simulation.core.runner import SimulationScenarioRunner


@pytest.fixture
def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def fast_config(tmp_path: Path) -> SimulationConfig:
    return SimulationConfig(
        report_dir=tmp_path / "reports", artifact_dir=tmp_path / "artifacts", time_step_sec=0.1
    )


@pytest.fixture
def runner(fast_config: SimulationConfig) -> SimulationScenarioRunner:
    return SimulationScenarioRunner(fast_config)


def scenario_path(package_root: Path, name: str) -> Path:
    return package_root / "scenarios" / f"{name}.yaml"
