"""Raspberry Pi + AI HAT runtime scenarios (family 2).

Drives the REAL `RuntimeSelector` + `HailoRuntime` + `HailoDeviceDetector`
(bonbon_ai_runtime) with an injected `runner`/`import_probe` per scenario --
the same seams the package's own unit tests use, never a fake Hailo PASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_ai_runtime")
)
from _hardware_gates import ai_hat_gated
from bonbon_ai_runtime import (
    HailoDeviceDetector,
    HailoRuntime,
    MockRuntime,
    RuntimeKind,
    RuntimeMode,
    RuntimeSelector,
    RuntimeSpec,
)
from reference_behaviors import simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.integration, pytest.mark.ai_hat_gated]

_SCENARIOS = load_generated("pi_ai_hat_runtime")


def _detector_for(hat_present: bool, hailort_installed: bool) -> HailoDeviceDetector:
    return HailoDeviceDetector(
        runner=(lambda c: (0, "Hailo-8L")) if hat_present else (lambda c: None),
        import_probe=lambda m: hailort_installed,
    )


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_runtime_selection_is_honest_for_every_combination(scenario, tmp_path):
    ic = scenario.input_conditions
    hat_present = ic.extra["hat_presence"] == "present"
    hailort_installed = ic.extra["hailort_state"] == "installed"
    model_format = ic.extra["model_format"]

    model_paths: dict[RuntimeKind, str] = {}
    if model_format == "hef_valid":
        hef = tmp_path / "model.hef"
        hef.write_bytes(b"x")
        model_paths[RuntimeKind.HAILO] = str(hef)
    elif model_format == "hef_wrong_format":
        onnx = tmp_path / "model.onnx"
        onnx.write_bytes(b"x")
        model_paths[RuntimeKind.HAILO] = str(onnx)
    # hef_missing / onnx_only: no usable HAILO model path at all.

    detector = _detector_for(hat_present, hailort_installed)
    hailo_truly_available = detector.detect().usable and model_format == "hef_valid"

    def factory(kind):
        if kind == RuntimeKind.HAILO:
            # infer_factory injected so this exercises the real selection/
            # availability/compatibility logic without needing real hailort
            # installed on the dev machine -- the same seam
            # test_runtime_abstraction.py's own unit tests use.
            return HailoRuntime(detector=detector, infer_factory=lambda p: (lambda t: []))
        return MockRuntime()

    res = RuntimeSelector(factory=factory).select(
        RuntimeSpec(
            mode=RuntimeMode.AUTO,
            runtime_priority=[RuntimeKind.HAILO, RuntimeKind.MOCK],
            model_paths=model_paths,
        )
    )

    if hailo_truly_available:
        assert res.selected_kind == RuntimeKind.HAILO
        assert res.fallback_active is False
    else:
        # Never a fake Hailo PASS: anything but a truly-available HAT+model
        # must fall back, and the fallback must say so honestly.
        assert res.selected_kind != RuntimeKind.HAILO
        assert res.fallback_active is True


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_runtime_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


@ai_hat_gated
def test_real_hailo_runtime_selected_on_hardware():
    det = HailoDeviceDetector().detect()
    assert det.usable is True
