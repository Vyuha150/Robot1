"""Hardware-gated tests for the Hailo AI HAT.

Behaviour by environment (the brief's requirement — never fake a PASS):

  * No Pi / no Hailo  → the on-device tests SKIP with a clear reason (they do
    NOT fail CI and do NOT report PASS). The off-device "no fake pass" tests
    run and assert the runtime honestly reports Hailo unavailable.
  * Pi with Hailo (`BONBON_HAILO_HW_TEST=1` AND a real device detected) →
    the on-device tests actually exercise detection / availability.

Gating uses the REAL HailoDeviceDetector (no mock), so the skip reason
reflects the actual machine.
"""

from __future__ import annotations

import os

import pytest
from bonbon_ai_runtime import (
    HailoDeviceDetector,
    HailoRuntime,
    RuntimeKind,
    RuntimeMode,
    RuntimeSelector,
    RuntimeSpec,
)

# Real (un-mocked) detection of THIS machine.
_REAL = HailoDeviceDetector().detect()
_HW_OPT_IN = os.environ.get("BONBON_HAILO_HW_TEST") == "1"

_run_on_device = pytest.mark.skipif(
    not (_HW_OPT_IN and _REAL.usable),
    reason=(
        "Hailo on-device test skipped: "
        + (
            "set BONBON_HAILO_HW_TEST=1 to opt in"
            if not _HW_OPT_IN
            else f"no usable Hailo device ({_REAL.detail})"
        )
        + ". This is BLOCKED, not failed — run on a Pi 5 + AI HAT."
    ),
)


# ── On-device (skipped off a real Pi+Hailo) ─────────────────────────────────
@_run_on_device
def test_hailo_device_detected_on_hardware():
    det = HailoDeviceDetector().detect()
    assert det.device_present is True
    assert det.runtime_available is True


@_run_on_device
def test_hailo_runtime_available_on_hardware():
    rt = HailoRuntime()
    assert rt.is_available().available is True


@_run_on_device
def test_hailo_selected_on_hardware():
    # On real hardware with a configured HEF, auto must pick hailo.
    hef = os.environ.get("BONBON_HAILO_HEF", "")
    if not hef:
        pytest.skip("set BONBON_HAILO_HEF to the .hef path for the on-device selection test")
    res = RuntimeSelector().select(
        RuntimeSpec(
            mode=RuntimeMode.AUTO,
            runtime_priority=[RuntimeKind.HAILO, RuntimeKind.CPU, RuntimeKind.MOCK],
            model_paths={RuntimeKind.HAILO: hef},
        )
    )
    assert res.selected_kind == RuntimeKind.HAILO
    assert res.fallback_active is False


# ── No-fake-PASS (always run; the heart of "don't lie about hardware") ──────
def test_no_fake_hailo_pass_without_device():
    """With the REAL detector and no opt-in/device, the Hailo runtime must
    report itself unavailable and selection must NOT pick hailo. This is the
    guard that the dashboard / benchmark can never show a Hailo PASS that
    isn't real."""
    if _HW_OPT_IN and _REAL.usable:
        pytest.skip("real Hailo present — covered by the on-device tests")
    rt = HailoRuntime()  # real detector
    assert rt.is_available().available is False
    res = RuntimeSelector().select(
        RuntimeSpec(mode=RuntimeMode.AUTO, runtime_priority=[RuntimeKind.HAILO, RuntimeKind.MOCK])
    )
    assert res.selected_kind != RuntimeKind.HAILO
    assert res.fallback_active is True


def test_benchmark_cli_marks_mock_fallback_nonzero():
    """The ai_runtime_bench CLI must exit non-zero when it silently fell back
    to mock (no real accelerator) in auto mode — so a CI/operator can't read
    a green exit as 'Hailo working'."""
    from bonbon_ai_runtime.cli import main

    if _HW_OPT_IN and _REAL.usable:
        pytest.skip("real Hailo present")
    rc = main(["--mode", "auto", "--runs", "3"])
    assert rc == 2  # fell back to mock → explicitly non-zero


def test_explicit_mock_mode_is_zero_exit():
    """Explicit mock mode is a legitimate request, not a silent fallback —
    exit 0."""
    from bonbon_ai_runtime.cli import main

    assert main(["--mode", "mock", "--runs", "3"]) == 0
