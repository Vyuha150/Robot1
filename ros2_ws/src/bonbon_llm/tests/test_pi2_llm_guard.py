"""Tests for Pi2LLMGuard -- the Qwen2.5 0.5B / Pi-2 hardware constraints
(max 1 concurrent request, max 64 output tokens, disable on high CPU/temp/
safety fault). Disabled by default so single-machine/monolithic deployment
behavior is unaffected unless explicitly enabled for Pi-2."""

from __future__ import annotations

import unittest

from bonbon_llm.core.pi2_llm_guard import Pi2LLMGuard, Pi2LLMGuardConfig


class TestPi2LLMGuardDisabledByDefault(unittest.TestCase):
    def setUp(self):
        self.guard = Pi2LLMGuard()  # default config: enabled=False

    def test_try_acquire_always_succeeds_when_disabled(self):
        for _ in range(10):
            self.assertTrue(self.guard.try_acquire())

    def test_clamp_max_tokens_is_a_no_op_when_disabled(self):
        self.assertEqual(self.guard.clamp_max_tokens(500), 500)

    def test_should_disable_always_false_when_disabled(self):
        d = self.guard.should_disable(cpu_percent=99.0, temp_c=99.0, safety_state_name="FAULT")
        self.assertFalse(d.disabled)


class TestPi2LLMGuardEnabled(unittest.TestCase):
    def setUp(self):
        self.guard = Pi2LLMGuard(Pi2LLMGuardConfig(enabled=True))

    def test_concurrency_limit_enforced(self):
        self.assertTrue(self.guard.try_acquire())  # 1st request: ok
        self.assertFalse(self.guard.try_acquire())  # 2nd concurrent: rejected

    def test_release_frees_the_slot(self):
        self.guard.try_acquire()
        self.guard.release()
        self.assertTrue(self.guard.try_acquire())

    def test_release_without_acquire_never_goes_negative(self):
        self.guard.release()
        self.guard.release()
        self.assertEqual(self.guard.in_flight, 0)

    def test_clamp_max_tokens_caps_at_64(self):
        self.assertEqual(self.guard.clamp_max_tokens(500), 64)

    def test_clamp_max_tokens_does_not_raise_a_lower_request(self):
        self.assertEqual(self.guard.clamp_max_tokens(10), 10)

    def test_disabled_in_danger_state(self):
        d = self.guard.should_disable(cpu_percent=10.0, temp_c=40.0, safety_state_name="DANGER")
        self.assertTrue(d.disabled)
        self.assertIn("DANGER", d.reason)

    def test_disabled_in_fault_state(self):
        d = self.guard.should_disable(cpu_percent=10.0, temp_c=40.0, safety_state_name="FAULT")
        self.assertTrue(d.disabled)

    def test_not_disabled_in_normal_state_within_limits(self):
        d = self.guard.should_disable(cpu_percent=10.0, temp_c=40.0, safety_state_name="NORMAL")
        self.assertFalse(d.disabled)

    def test_disabled_when_cpu_at_threshold(self):
        d = self.guard.should_disable(cpu_percent=85.0, temp_c=40.0, safety_state_name="NORMAL")
        self.assertTrue(d.disabled)
        self.assertIn("CPU", d.reason)

    def test_not_disabled_just_below_cpu_threshold(self):
        d = self.guard.should_disable(cpu_percent=84.9, temp_c=40.0, safety_state_name="NORMAL")
        self.assertFalse(d.disabled)

    def test_disabled_when_temp_at_threshold(self):
        d = self.guard.should_disable(cpu_percent=10.0, temp_c=75.0, safety_state_name="NORMAL")
        self.assertTrue(d.disabled)
        self.assertIn("temp", d.reason)

    def test_caution_state_does_not_disable(self):
        # CAUTION is not in the disable set -- LLM should keep working,
        # only DANGER/FAULT/SAFE_STOP disable it.
        d = self.guard.should_disable(cpu_percent=10.0, temp_c=40.0, safety_state_name="CAUTION")
        self.assertFalse(d.disabled)


class TestPi2LLMGuardConfigValidation(unittest.TestCase):
    def test_rejects_zero_concurrency(self):
        with self.assertRaises(ValueError):
            Pi2LLMGuardConfig(max_concurrent_requests=0).validate()

    def test_rejects_zero_max_tokens(self):
        with self.assertRaises(ValueError):
            Pi2LLMGuardConfig(max_output_tokens=0).validate()

    def test_rejects_nonpositive_timeout(self):
        with self.assertRaises(ValueError):
            Pi2LLMGuardConfig(initial_timeout_sec=0.0).validate()

    def test_default_config_matches_brief_exactly(self):
        cfg = Pi2LLMGuardConfig()
        self.assertEqual(cfg.max_concurrent_requests, 1)
        self.assertEqual(cfg.max_output_tokens, 64)
        self.assertEqual(cfg.initial_timeout_sec, 1.0)
        self.assertEqual(cfg.disable_safety_states, frozenset({"DANGER", "FAULT", "SAFE_STOP"}))


if __name__ == "__main__":
    unittest.main()
