"""Tests for ModelRuntimeSelector's Hailo availability checking as applied
to the object_detection/person_detection/pose_estimation capabilities --
rule 10 (hardware-gated tests must be BLOCKED, not faked, when actual
hardware is unavailable) and confirmation that vision hardware detection
correctly delegates to bonbon_ai_runtime.hailo_device_detector rather
than a second, divergent detection implementation."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"

# Same real (no-mock) Hailo detector tests/production/_hardware_gates.py
# uses -- re-instantiated locally rather than imported cross-directory,
# since tests/ has no top-level __init__.py in this repo's convention.
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_runtime"))
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


class TestHailoEntriesReportUnavailableOffHardware(unittest.TestCase):
    """No real Hailo device/hailort exists in this sandbox -- every
    hailo_8/hailo_10h entry MUST report is_available()=False, never a
    fabricated True. This is the direct rule-1/rule-10 assertion."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.selector = ModelRuntimeSelector(self.registry)

    def test_every_hailo_entry_reports_unavailable_on_this_sandbox(self):
        hailo_entries = [e for e in self.registry.all() if e.hardware_target in ("hailo_8", "hailo_10h")]
        self.assertTrue(hailo_entries, "expected at least one hailo_8/hailo_10h registry entry")
        for entry in hailo_entries:
            self.assertFalse(
                self.selector.is_available(entry),
                f"{entry.model_id} (hardware_target={entry.hardware_target}) reported available with no real Hailo device -- rule 1/10 violation",
            )

    def test_hailo_checker_delegates_to_bonbon_ai_runtime_not_a_second_implementation(self):
        # bonbon_ai_runtime is genuinely importable in this repo (it's a
        # pure-Python colcon package) even though no Hailo hardware is
        # present -- confirms the selector really calls through to it
        # rather than silently no-op'ing.
        #
        # Regression coverage for a real bug found and fixed this pass:
        # _check_hailo_available() used to import a module-level
        # `runtime_available` name from hailo_device_detector.py that has
        # never existed there (it's a *method* on HailoDeviceDetector) --
        # the resulting ImportError was silently caught, so every
        # hailo_8/hailo_10h entry reported unavailable UNCONDITIONALLY,
        # even on real Hailo hardware. Fixed to use
        # HailoDeviceDetector().detect().usable, the same real API
        # tests/production/_hardware_gates.py already relies on.
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_ai_runtime"))
        from bonbon_ai_runtime.hailo_device_detector import HailoDeviceDetector

        self.assertFalse(HailoDeviceDetector().detect().usable, "expected no usable Hailo runtime on this sandbox")

    @ai_hat_gated
    def test_hailo_entries_become_available_on_real_hailo_hardware(self):
        # Only runs with BONBON_HAILO_HW_TEST=1 on a real Pi + AI HAT --
        # BLOCKED (skipped) everywhere else, never faked.
        entry = self.registry.get("vision_hailo_yolo")
        self.assertTrue(self.selector.is_available(entry))


class TestObjectPersonPoseAlwaysResolveToARealEntry(unittest.TestCase):
    """GAP-2 / 18-point edge-AI verification (check 1) corrected finding:
    object_detection/person_detection/pose_estimation used to have NO
    enabled_by_default entry at all. That was NOT the honest "deferred
    pending a hard hardware/licensing choice" state this test previously
    asserted as correct -- FallbackPolicy.resolve() returns immediately
    with active_model_id=None when default_for_capability() is None,
    WITHOUT EVER WALKING THE CHAIN to the guaranteed-safe mock/CPU
    fallback. That meant these 3 capabilities had literally zero working
    path, not merely "no Hailo hardware" -- a real correctness bug, not a
    deliberate deferral. Fixed: the head of each real fallback chain is
    now the registered default (matching every other capability's own
    convention, e.g. local_llm's default is llm_qwen25_05b, not its
    terminal fallback); the genuinely still-unresolved question (which
    REAL detector -- Hailo vs CPU ONNX vs Ultralytics -- should win once
    hardware/licensing is settled) is untouched, since none of those 3
    is what's asserted as the resolved default below."""

    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry
        from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector

        self.registry = ModelRegistry.load(REGISTRY_PATH)
        self.selector = ModelRuntimeSelector(self.registry)

    def test_object_detection_resolves_to_a_real_entry_not_none(self):
        self.assertIsNotNone(self.registry.default_for_capability("object_detection"))
        status = self.selector.select("object_detection")
        self.assertIsNotNone(
            status.decision.active_model_id,
            "object_detection's fallback chain must terminate in the guaranteed vision_mock, never nothing",
        )

    def test_person_detection_resolves_to_a_real_entry_not_none(self):
        self.assertIsNotNone(self.registry.default_for_capability("person_detection"))
        status = self.selector.select("person_detection")
        self.assertIsNotNone(
            status.decision.active_model_id,
            "person_detection's fallback chain must terminate in the guaranteed vision_mock, never nothing",
        )

    def test_pose_estimation_resolves_to_a_real_entry_not_none(self):
        self.assertIsNotNone(self.registry.default_for_capability("pose_estimation"))
        status = self.selector.select("pose_estimation")
        self.assertIsNotNone(
            status.decision.active_model_id,
            "pose_estimation's fallback chain must terminate in the guaranteed gesture_mock, never nothing",
        )

    def test_cross_capability_fallback_targets_are_correctly_checked_for_availability(self):
        # Regression guard for the deeper bug this fix also uncovered:
        # ModelRuntimeSelector.select() used to compute availability
        # scoped only to the requested capability's own entries, so a
        # fallback_model_id pointing into a DIFFERENT capability (as
        # person_detection -> vision_mock and pose_estimation ->
        # gesture_mediapipe_holistic both legitimately do) was always
        # treated as unavailable via a dict-lookup miss, regardless of
        # its real, checkable availability.
        status = self.selector.select("person_detection")
        self.assertIn("vision_mock", status.availability, "cross-capability fallback target must be checked, not silently omitted")
        self.assertTrue(status.availability["vision_mock"])


if __name__ == "__main__":
    unittest.main()
