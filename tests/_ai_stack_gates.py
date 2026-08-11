"""Shared skip-gate markers for the Phase 13 AI-model-stack test suite
(tests/ai_models, tests/speech_ai, tests/llm_local, tests/perception_ai,
tests/gesture_ai, tests/affective_ai, tests/dashboard).

Not a test_ file itself (pytest won't collect it). Mirrors
tests/production/_hardware_gates.py's pattern exactly: every real
dependency this environment might be missing (Ollama, torch, mediapipe,
faster-whisper, DeepFace/SpeechBrain, a real Hailo device) gets its own
skipif gate with an honest, opt-in-aware reason string. A test skipped
here means "BLOCKED -- not available on this machine", never a silent
pass and never a fabricated failure. Consistent with rule 1 (never fake
model availability) and rule 10 (hardware-gated tests must be BLOCKED
when hardware is unavailable) applied to the test suite itself.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_runtime"))

# Same real Hailo detector tests/production/_hardware_gates.py uses (no
# mock) -- re-instantiated locally rather than imported cross-package
# from tests.production, since tests/ has no top-level __init__.py and
# this repo's convention keeps test directories independently importable.
from bonbon_ai_runtime import HailoDeviceDetector  # noqa: E402

_HAILO_REAL = HailoDeviceDetector().detect()
_HAILO_HW_OPT_IN = os.environ.get("BONBON_HAILO_HW_TEST") == "1"

ai_hat_gated = pytest.mark.skipif(
    not (_HAILO_HW_OPT_IN and _HAILO_REAL.usable),
    reason=(
        "AI-HAT-gated test skipped: "
        + ("set BONBON_HAILO_HW_TEST=1 to opt in" if not _HAILO_HW_OPT_IN else f"no usable Hailo device ({_HAILO_REAL.detail})")
        + ". This is BLOCKED, not failed -- run on a Pi 5 + AI HAT."
    ),
)


def _pip_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _gate(module_name: str, human_name: str | None = None):
    label = human_name or module_name
    return pytest.mark.skipif(
        not _pip_available(module_name),
        reason=f"{label} not installed in this environment -- BLOCKED, not failed. Install via requirements/pi2_requirements.txt on real Pi-2 hardware.",
    )


torch_gated = _gate("torch")
mediapipe_gated = _gate("mediapipe")
faster_whisper_gated = _gate("faster_whisper", "faster-whisper")
deepface_gated = _gate("deepface", "DeepFace")
speechbrain_gated = _gate("speechbrain", "SpeechBrain")
onnxruntime_gated = _gate("onnxruntime")

ollama_gated = pytest.mark.skipif(
    shutil.which("ollama") is None,
    reason="ollama binary not on PATH in this environment -- BLOCKED, not failed. See docs/PI2_QWEN25_05B_SETUP_REPORT.md for the real Pi-2 result.",
)

rclpy_gated = pytest.mark.skipif(
    not _pip_available("rclpy"),
    reason="rclpy not installed -- this is a colcon/ROS2-only test, BLOCKED off a sourced ROS2 environment.",
)
