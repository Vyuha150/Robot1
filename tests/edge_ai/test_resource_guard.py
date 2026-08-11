"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.resource_guard.
ResourceGuard is a read-only facade over real, already-tested
ResourceMonitor/LoadSheddingController/Pi2LLMGuard -- these tests check
the facade wires evaluate() through correctly and honestly, not that
psutil returns any particular number (that's the underlying components'
own test suites' job)."""

from __future__ import annotations

import unittest


class TestResourceGuardFacade(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.resource_guard import ResourceGuard

        self.guard = ResourceGuard()

    def test_evaluate_returns_all_required_fields(self):
        status = self.guard.evaluate(temp_c=40.0, safety_state_name="SAFETY_NORMAL", safety_caution_or_above=False)
        as_dict = status.to_dict()
        for field in (
            "cpuPercent", "memoryPercent", "diskFreePercent", "tempC", "metricsAvailable",
            "loadLevel", "loadScale", "loadReason", "llmDisabled", "llmDisableReason",
        ):
            self.assertIn(field, as_dict)

    def test_thermal_overload_above_fault_threshold_escalates_load_level_when_metrics_are_real(self):
        # LoadSheddingController's own "resource metrics unavailable --
        # never shed load on missing data" rule wins over thermal on a
        # dev machine without real psutil disk/cpu metrics for this
        # data_path (e.g. Windows) -- so this only asserts escalation
        # when metrics genuinely are available; otherwise it asserts the
        # honest opposite (never fabricate an alarm from missing data).
        overheated = self.guard.evaluate(temp_c=95.0, safety_state_name="SAFETY_NORMAL", safety_caution_or_above=False)
        if overheated.metrics_available:
            self.assertNotEqual(overheated.load_level, "normal")
        else:
            self.assertEqual(overheated.load_level, "normal")

    def test_llm_guard_property_exposes_underlying_pi2_llm_guard(self):
        # Callers needing try_acquire()/release()/clamp_max_tokens() must
        # get the SAME instance evaluate() uses, not a second disconnected one.
        self.assertIs(self.guard.llm_guard, self.guard._llm_guard)

    def test_custom_thermal_fault_threshold_is_respected_when_metrics_are_real(self):
        from bonbon_edge_ai_runtime.resource_guard import ResourceGuard

        strict_guard = ResourceGuard(thermal_fault_c=50.0)
        status = strict_guard.evaluate(temp_c=60.0, safety_state_name="SAFETY_NORMAL", safety_caution_or_above=False)
        if status.metrics_available:
            self.assertNotEqual(status.load_level, "normal")
        else:
            self.assertEqual(status.load_level, "normal")


if __name__ == "__main__":
    unittest.main()
