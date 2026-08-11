"""Shared fixtures for tests/safety/ -- points sys.path at the colcon-only
packages whose pure safety-decision logic these tests chain together."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "ros2_ws" / "src"

for _extra in (
    _SRC / "bonbon_behavior_engine",
    _SRC / "bonbon_motion_approval_gateway",
    _SRC / "bonbon_navigation",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))
