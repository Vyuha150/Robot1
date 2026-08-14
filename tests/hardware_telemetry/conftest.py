"""Shared fixtures for tests/hardware_telemetry/ -- points sys.path at
bonbon_hardware_telemetry (real, checked-in package, no colcon build in
this dev sandbox), matching the pattern in tests/edge_ai/conftest.py."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "ros2_ws" / "src"

for _extra in (
    _SRC / "bonbon_hardware_telemetry",
    _SRC / "bonbon_safety",
    _SRC / "bonbon_hal",
    _SRC / "bonbon_msgs",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

THRESHOLDS_PATH = _REPO_ROOT / "config" / "hardware_telemetry" / "thresholds.yaml"
