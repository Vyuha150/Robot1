"""Make the sibling AI/robot packages importable for cross-cutting scenario tests.

The scenario suite exercises the real pure-Python decision cores from several
packages together. Their cores have no rclpy dependency, so adding each package
root to sys.path is sufficient to import them in a plain pytest environment.
"""

from __future__ import annotations

import os
import sys

import pytest

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _pkg in (
    "bonbon_safety", "bonbon_behavior_engine", "bonbon_actuation",
    "bonbon_gesture", "bonbon_spatial",
):
    _p = os.path.join(_SRC, _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _deterministic():
    """Seed RNG before every scenario for reproducibility (no flaky tests)."""
    from bonbon_safety.testkit.scenario import seed
    seed()
