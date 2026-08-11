"""Tests for the local Qwen2.5 0.5B LLM's safety envelope -- rule 5 (LLM
must never directly control navigation/motors/servos/safety) and rule 7
(never bypass the Safety Supervisor). Two things are verified together:
(1) the registry actually selects llm_qwen25_05b as the real local_llm
default this guard applies to, and (2) bonbon_llm's existing
SafetyCommandFilter/Pi2LLMGuard -- which every LLM output must pass
through before dispatch -- correctly blocks direct hardware/navigation
control text and correctly disables the LLM under unsafe load/safety
conditions. Both halves are pure Python, no rclpy/Ollama required."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry",
    _REPO_ROOT / "ros2_ws" / "src" / "bonbon_llm",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"


class TestQwenIsTheRealRegisteredLocalLLM(unittest.TestCase):
    def setUp(self):
        from bonbon_ai_model_registry.model_registry import ModelRegistry

        self.registry = ModelRegistry.load(REGISTRY_PATH)

    def test_qwen25_05b_is_the_enabled_default_local_llm(self):
        default = self.registry.default_for_capability("local_llm")
        self.assertEqual(default.model_id, "llm_qwen25_05b")

    def test_qwen25_05b_has_no_fallback_to_a_larger_model(self):
        # local_llm has exactly one enabled_by_default entry and no
        # automatic fallback to llm_qwen25_15b/llm_llama32_1b -- those are
        # benchmark-only candidates requiring explicit human approval to
        # even download (see tests/ai_models/test_license_guard.py), not
        # something the runtime silently escalates to.
        entry = self.registry.get("llm_qwen25_05b")
        self.assertIsNone(entry.fallback_model_id)

    def test_registry_grants_the_llm_no_actuation_authority_fields(self):
        # The ModelEntry schema itself has no field that could grant an LLM
        # entry direct navigation/actuation authority (e.g. no
        # "can_control_motors" flag exists to even misconfigure) --
        # confirms rule 5 is structural, not just a convention.
        import dataclasses

        from bonbon_ai_model_registry.model_registry import ModelEntry

        field_names = {f.name for f in dataclasses.fields(ModelEntry)}
        for forbidden in ("actuator", "motor", "servo", "navigation_authority", "safety_override"):
            self.assertFalse(
                any(forbidden in f for f in field_names),
                f"ModelEntry schema unexpectedly has a field resembling {forbidden!r}",
            )


class TestSafetyCommandFilterBlocksLLMHardwareControl(unittest.TestCase):
    """Every piece of LLM output must pass through this filter before
    dispatch (bonbon_llm.safety.command_filter's own module docstring) --
    this is the real enforcement mechanism for rule 5/7, tested directly
    against realistic Qwen-style outputs a small local model might
    plausibly hallucinate."""

    def setUp(self):
        from bonbon_llm.config.llm_config import SafetyFilterConfig
        from bonbon_llm.safety.command_filter import SafetyCommandFilter

        self.filt = SafetyCommandFilter(SafetyFilterConfig())

    def test_direct_velocity_command_text_is_blocked(self):
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_text("Sure, publishing cmd_vel with linear.x=1.0 to move forward.")
        self.assertEqual(result.status, FilterStatus.BLOCKED)

    def test_direct_navigate_to_pose_text_is_blocked(self):
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_text("Calling navigate_to_pose directly to reach the front desk.")
        self.assertEqual(result.status, FilterStatus.BLOCKED)

    def test_safety_bypass_language_is_blocked(self):
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_text("I will override safety and disable the estop for you.")
        self.assertEqual(result.status, FilterStatus.BLOCKED)

    def test_ordinary_conversational_reply_is_safe(self):
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_text("I am BonBon, ready to help. The cardiology department is on the second floor.")
        self.assertEqual(result.status, FilterStatus.SAFE)

    def test_direct_hardware_behavior_class_is_blocked(self):
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_behavior("direct_motor_control", confidence=0.99)
        self.assertEqual(result.status, FilterStatus.BLOCKED)

    def test_navigate_to_behavior_class_is_risky_not_auto_dispatched(self):
        # Even a legitimate navigation INTENT must go through Safety
        # Supervisor authorization (RISKY), never SAFE-auto-dispatch.
        from bonbon_llm.safety.command_filter import FilterStatus

        result = self.filt.filter_behavior("navigate_to", confidence=0.95)
        self.assertEqual(result.status, FilterStatus.RISKY)


class TestPi2LLMGuardDisablesUnderUnsafeConditions(unittest.TestCase):
    def setUp(self):
        from bonbon_llm.core.pi2_llm_guard import Pi2LLMGuard, Pi2LLMGuardConfig

        self.guard = Pi2LLMGuard(Pi2LLMGuardConfig(enabled=True))

    def test_disabled_when_safety_state_is_fault(self):
        decision = self.guard.should_disable(cpu_percent=10.0, temp_c=40.0, safety_state_name="FAULT")
        self.assertTrue(decision.disabled)

    def test_output_tokens_are_clamped_when_enabled(self):
        clamped = self.guard.clamp_max_tokens(10_000)
        self.assertLessEqual(clamped, self.guard.config.max_output_tokens)


if __name__ == "__main__":
    unittest.main()
