"""Validates the config/runtime/*.yaml model-runtime mapping files: they
parse, carry the keys bonbon_ai_runtime.RuntimeSelector expects, and every
declared runtime / mode is a real one the package knows about. Keeps the
config honest (no typo'd runtime names, no model entry missing its priority
list) without needing a Pi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / "config" / "runtime"

# Valid runtime kinds / modes the package supports (kept in sync with
# bonbon_ai_runtime without importing it — devops tests don't depend on the
# ROS2 packages being on the path).
VALID_RUNTIMES = {"hailo", "cpu", "tensorrt", "mock"}
VALID_MODES = {"auto", "cpu", "hailo", "tensorrt", "mock"}


def _load(name: str) -> dict:
    return yaml.safe_load((RUNTIME_DIR / name).read_text(encoding="utf-8"))


def test_all_runtime_configs_parse():
    for f in RUNTIME_DIR.glob("*.yaml"):
        assert isinstance(yaml.safe_load(f.read_text(encoding="utf-8")), dict), f.name


def test_model_runtime_mode_is_valid():
    cfg = _load("model_runtime.yaml")
    assert cfg["runtime"]["mode"] in VALID_MODES


def test_every_model_has_a_valid_runtime_priority():
    cfg = _load("model_runtime.yaml")
    assert cfg["models"], "no models declared"
    for name, spec in cfg["models"].items():
        prio = spec.get("runtime_priority")
        assert prio, f"{name} missing runtime_priority"
        for rt in prio:
            assert rt in VALID_RUNTIMES, f"{name}: unknown runtime '{rt}'"
        # mock must be reachable as the final safety net (directly or via auto)
        assert "mock" in prio or cfg["runtime"]["mode"] == "auto"


def test_hailo_models_declare_hef_paths():
    cfg = _load("model_runtime.yaml")
    for name, spec in cfg["models"].items():
        if "hailo" in spec.get("runtime_priority", []):
            assert spec.get("hailo_hef_path", "").endswith(".hef"), f"{name} hef path"


def test_cpu_models_declare_onnx_paths():
    cfg = _load("model_runtime.yaml")
    for name, spec in cfg["models"].items():
        if "cpu" in spec.get("runtime_priority", []):
            # mock_test_model is the only one that legitimately has no onnx
            if name == "mock_test_model":
                continue
            assert spec.get("cpu_onnx_path", "").endswith(".onnx"), f"{name} onnx path"


def test_pi_ai_hat_prefers_hailo():
    cfg = _load("pi_ai_hat.yaml")
    assert cfg["runtime"]["preferred_accelerator"] == "hailo"
    assert cfg["hailo"]["enabled"] is True
    assert cfg["models_default_runtime_priority"][0] == "hailo"


def test_pi_cpu_fallback_disables_hailo():
    cfg = _load("pi_cpu_fallback.yaml")
    assert cfg["runtime"]["mode"] == "cpu"
    assert cfg["hailo"]["enabled"] is False
    assert "hailo" not in cfg["models_default_runtime_priority"]


def test_degraded_mode_never_disables_safety():
    cfg = _load("degraded_mode.yaml")["degraded_mode"]
    never = set(cfg["never_disable"])
    assert {"safety_supervisor", "emergency_stop"} <= never
    # Nothing in never_disable may also appear in shed_order.
    assert never.isdisjoint(set(cfg["shed_order"]))


def test_fail_open_to_degraded_mode_is_set_on_pi_profiles():
    for name in ("model_runtime.yaml", "pi_ai_hat.yaml", "pi_cpu_fallback.yaml"):
        cfg = _load(name)
        assert cfg["runtime"]["fail_open_to_degraded_mode"] is True, name


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
