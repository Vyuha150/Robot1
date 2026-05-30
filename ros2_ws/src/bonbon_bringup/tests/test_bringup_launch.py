"""Tests for the bonbon_bringup top-level launch file.

These run in a plain (non-ROS2) environment: they statically validate that the
launch file declares the expected arguments and composes every subsystem, which
guards against a subsystem being silently dropped from system bring-up. When the
ROS2 ``launch`` package *is* importable (i.e. in CI on a sourced workspace), an
extra test additionally constructs the LaunchDescription for real.
"""

from __future__ import annotations

import ast
import importlib.util
import os

import pytest

_LAUNCH_FILE = os.path.join(
    os.path.dirname(__file__), "..", "launch", "bringup.launch.py"
)

# Every subsystem that MUST be part of system bring-up.
_REQUIRED_SUBSYSTEMS = [
    "bonbon_data_stores",
    "bonbon_safety",
    "bonbon_hal",
    "bonbon_vision",
    "bonbon_speech",
    "bonbon_spatial",
    "bonbon_affective_ai",
    "bonbon_gesture",
    "bonbon_perception_ai",
    "bonbon_llm",
    "bonbon_behavior_engine",
    "bonbon_actuation",
    "bonbon_navigation",
    "bonbon_tts",
    "bonbon_operator_api",
]

_REQUIRED_ARGS = [
    "simulation",
    "enable_navigation",
    "enable_ai",
    "enable_operator_api",
    "log_level",
]


@pytest.fixture(scope="module")
def source() -> str:
    with open(_LAUNCH_FILE, "r", encoding="utf-8") as f:
        return f.read()


class TestLaunchStructure:
    def test_file_exists(self):
        assert os.path.isfile(_LAUNCH_FILE)

    def test_is_valid_python(self, source):
        # Must parse — a broken launch file would fail at deploy time.
        ast.parse(source)

    def test_defines_generate_launch_description(self, source):
        tree = ast.parse(source)
        funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "generate_launch_description" in funcs

    def test_declares_all_launch_arguments(self, source):
        for arg in _REQUIRED_ARGS:
            assert f'"{arg}"' in source, f"launch arg '{arg}' not declared"

    def test_includes_every_subsystem(self, source):
        for pkg in _REQUIRED_SUBSYSTEMS:
            assert f'"{pkg}"' in source, f"subsystem '{pkg}' missing from bring-up"

    def test_safety_started_before_actuation(self, source):
        # Safety must be composed before actuation/navigation in the file.
        assert source.index("bonbon_safety") < source.index("bonbon_actuation")
        assert source.index("bonbon_data_stores") < source.index("bonbon_behavior_engine")


# ament_index_python is strictly a ROS2 package — its presence is a reliable
# signal that a workspace has been sourced (unlike the generic PyPI 'launch').
@pytest.mark.skipif(
    importlib.util.find_spec("ament_index_python") is None
    or importlib.util.find_spec("launch_ros") is None,
    reason="ROS2 not available (run on a sourced workspace)",
)
class TestLaunchConstructsUnderRos2:
    def test_generate_launch_description_returns_description(self):
        try:
            spec = importlib.util.spec_from_file_location("bringup_launch", _LAUNCH_FILE)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            from launch import LaunchDescription
        except ImportError as exc:  # pragma: no cover - env-dependent
            pytest.skip(f"ROS2 launch imports unavailable: {exc}")

        ld = mod.generate_launch_description()
        assert isinstance(ld, LaunchDescription)
        assert len(ld.entities) > 0
