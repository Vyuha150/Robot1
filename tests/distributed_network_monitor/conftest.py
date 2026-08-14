"""Shared fixtures for tests/distributed_network_monitor/ -- points
sys.path at bonbon_distributed_network_monitor (real, checked-in
package, no colcon build in this dev sandbox), matching the pattern in
tests/hardware_telemetry/conftest.py."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "ros2_ws" / "src" / "bonbon_distributed_network_monitor"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

ROBOT_NETWORK_CONFIG_PATH = _REPO_ROOT / "config" / "distributed" / "robot_network.yaml"
