"""Shared fixtures for tests/ai_models/ -- points sys.path at the new
bonbon_ai_model_registry / bonbon_sarvam_adapter packages (colcon-only
packages, not pip-installed) and exposes the real, checked-in
config/models/model_registry.yaml so tests exercise the actual authored
config, never a synthetic stand-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_sarvam_adapter",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"


@pytest.fixture
def registry():
    from bonbon_ai_model_registry.model_registry import ModelRegistry

    return ModelRegistry.load(REGISTRY_PATH)
