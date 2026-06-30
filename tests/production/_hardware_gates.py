"""Shared hardware-gate skip markers for tests/production/*.

Not a test_ file itself (pytest won't collect it). Two gates:

  * `pi_gated`     -- needs a real Raspberry Pi (`BONBON_PI_HW_TEST=1` opt-in
                       AND `/proc/device-tree/model` says "Raspberry Pi").
  * `ai_hat_gated` -- needs a real Hailo AI HAT, using the same REAL
                       HailoDeviceDetector as bonbon_ai_runtime's
                       test_hardware_gated.py (no mock).

Off the named hardware both SKIP with a "BLOCKED, not failed" reason --
they never silently pass and never silently disappear from the report.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_runtime"))
from bonbon_ai_runtime import HailoDeviceDetector  # noqa: E402

_PI_HW_OPT_IN = os.environ.get("BONBON_PI_HW_TEST") == "1"


def _looks_like_raspberry_pi() -> bool:
    model_path = Path("/proc/device-tree/model")
    if not model_path.exists():
        return False
    try:
        return "raspberry pi" in model_path.read_text(errors="ignore").lower()
    except OSError:
        return False


_ON_PI = _looks_like_raspberry_pi()

pi_gated = pytest.mark.skipif(
    not (_PI_HW_OPT_IN and _ON_PI),
    reason=(
        "Pi-gated test skipped: "
        + (
            "set BONBON_PI_HW_TEST=1 to opt in"
            if not _PI_HW_OPT_IN
            else "not running on a detected Raspberry Pi"
        )
        + ". This is BLOCKED, not failed -- run on a Pi 5."
    ),
)

_HAILO_REAL = HailoDeviceDetector().detect()
_HAILO_HW_OPT_IN = os.environ.get("BONBON_HAILO_HW_TEST") == "1"

ai_hat_gated = pytest.mark.skipif(
    not (_HAILO_HW_OPT_IN and _HAILO_REAL.usable),
    reason=(
        "AI-HAT-gated test skipped: "
        + (
            "set BONBON_HAILO_HW_TEST=1 to opt in"
            if not _HAILO_HW_OPT_IN
            else f"no usable Hailo device ({_HAILO_REAL.detail})"
        )
        + ". This is BLOCKED, not failed -- run on a Pi 5 + AI HAT."
    ),
)
