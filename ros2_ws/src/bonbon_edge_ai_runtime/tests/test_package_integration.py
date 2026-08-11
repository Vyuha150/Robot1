"""Integration smoke test for the whole bonbon_edge_ai_runtime package
(Phase 2). Exercises every module together against the real
config/edge_ai/*.yaml files and the real, merged
config/models/model_registry.yaml -- not mocks. Per-module unit tests
with the 22 specific required assertions live in tests/edge_ai/ (repo
root, Phase 13); this file only proves the package wires together and
the Phase 1 audit's "consolidate, don't duplicate" plan actually holds
at runtime.
"""

from __future__ import annotations

import unittest


class TestConfigLoader(unittest.TestCase):
    def test_all_eight_edge_ai_config_files_load(self):
        from bonbon_edge_ai_runtime.config_loader import EdgeAIConfig

        cfg = EdgeAIConfig.load()
        self.assertTrue(cfg.all_files_present(), f"missing: {cfg.missing_files()}")
        for name in (
            "model_registry",
            "task_routing",
            "runtime_profiles",
            "cache_policy",
            "resource_limits",
            "safety_separation",
            "degraded_modes",
            "three_pi_allocation",
        ):
            self.assertIsInstance(cfg[name], dict)


class TestModelRegistryMerge(unittest.TestCase):
    def test_merged_registry_has_19_capabilities_and_no_validation_problems(self):
        from bonbon_edge_ai_runtime.model_registry import CAPABILITIES, load_merged

        registry = load_merged()
        self.assertEqual(registry.validate(), [])
        self.assertEqual(len(CAPABILITIES), 19)
        self.assertGreaterEqual(len(registry.all()), 45)  # 39 original + 6 edge-ai

    def test_three_new_capabilities_each_have_a_default_and_a_fallback(self):
        from bonbon_edge_ai_runtime.model_registry import load_merged

        registry = load_merged()
        for capability in ("human_state_fusion", "intent_classification", "assistant_guardrails"):
            default = registry.default_for_capability(capability)
            self.assertIsNotNone(default, f"{capability} has no enabled_by_default entry")
            self.assertIsNotNone(default.fallback_model_id, f"{capability}'s default has no fallback")


class TestSafetySeparationGuard(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

        self.guard = SafetySeparationGuard()

    def test_llm_direct_motor_command_blocked(self):
        result = self.guard.classify("llm", "direct_motor_command")
        self.assertTrue(result.blocked)
        self.assertEqual(result.category.value, "UNSAFE_DIRECT_CONTROL")

    def test_llm_direct_servo_command_blocked(self):
        result = self.guard.classify("llm", "direct_servo_command")
        self.assertTrue(result.blocked)
        self.assertEqual(result.category.value, "UNSAFE_DIRECT_CONTROL")

    def test_ui_direct_motor_command_blocked(self):
        result = self.guard.classify("ui", "direct_motor_command")
        self.assertTrue(result.blocked)

    def test_ui_raw_nav2_goal_blocked(self):
        result = self.guard.classify("ui", "raw_nav2_goal")
        self.assertTrue(result.blocked)

    def test_ai_pi_direct_navigation_command_blocked(self):
        result = self.guard.classify("ai_pi_perception", "direct_navigation_command")
        self.assertTrue(result.blocked)
        self.assertEqual(result.category.value, "UNSAFE_DIRECT_CONTROL")

    def test_blocked_action_visible_in_dashboard_summary(self):
        self.guard.classify("llm", "direct_motor_command")
        self.guard.classify("ui", "raw_nav2_goal")
        summary = self.guard.summary()
        self.assertGreaterEqual(summary["totalBlocked"], 2)
        reasons = [entry["actionType"] for entry in summary["recentBlocked"]]
        self.assertIn("direct_motor_command", reasons)
        self.assertIn("raw_nav2_goal", reasons)

    def test_safety_supervisor_direct_control_allowed(self):
        result = self.guard.classify("safety_supervisor", "direct_motor_command")
        self.assertFalse(result.blocked)
        self.assertEqual(result.category.value, "SAFETY_CRITICAL")

    def test_navigation_proposal_allowed_but_requires_approval(self):
        result = self.guard.classify("ai_pi_gesture", "navigation_request")
        self.assertFalse(result.blocked)
        self.assertTrue(result.requires_approval)

    def test_unrecognized_action_type_fails_closed(self):
        result = self.guard.classify("llm", "some_new_action_nobody_registered")
        self.assertTrue(result.blocked)


class TestTaskRouter(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.task_router import TaskRouter

        self.router = TaskRouter()

    def test_emergency_routes_to_deterministic_rule_not_llm(self):
        decision = self.router.route_text_intent("help, someone collapsed")
        self.assertEqual(decision.task_type, "emergency")
        self.assertNotEqual(decision.chosen_method.value, "tiny_local_llm")

    def test_where_is_routes_to_info_lookup_not_navigation(self):
        decision = self.router.route_text_intent("Where is Cardiology?")
        self.assertEqual(decision.task_type, "faq")

    def test_guide_me_to_routes_to_navigation_and_requires_safety(self):
        decision = self.router.route_text_intent("Guide me to room 203")
        self.assertEqual(decision.task_type, "navigation")
        self.assertTrue(decision.safety_required)

    def test_appointment_booking_never_uses_llm(self):
        decision = self.router.route_text_intent("Book appointment with Dr. Rao")
        self.assertNotEqual(decision.chosen_method.value, "tiny_local_llm")

    def test_stop_palm_gesture_is_safety_relevant(self):
        decision = self.router.route_gesture("stop_palm", confidence=0.9)
        self.assertTrue(decision.safety_required)

    def test_unknown_gesture_takes_no_action(self):
        decision = self.router.route_gesture("not_a_real_gesture", confidence=0.9)
        self.assertEqual(decision.chosen_method.value, "degraded_fallback_template")

    def test_low_confidence_emotion_does_not_strongly_change_behavior(self):
        decision = self.router.route_emotion("angry", confidence=0.2)
        self.assertIn("no behavior change", decision.reason)


class TestEdgeAiRuntimeNodeSafetyCautionDerivation(unittest.TestCase):
    """18-point edge-AI verification, check 14: edge_ai_runtime_node's
    resource_guard dashboard view previously hardcoded
    safety_caution_or_above=False regardless of real safety state --
    this is the pure decision function that replaced it."""

    def setUp(self):
        from bonbon_edge_ai_runtime.nodes.edge_ai_runtime_node import (
            SAFETY_CAUTION_LEVEL,
            derive_safety_caution_or_above,
        )

        self.derive = derive_safety_caution_or_above
        self.CAUTION = SAFETY_CAUTION_LEVEL

    def test_no_message_ever_received_fails_toward_caution(self):
        self.assertTrue(self.derive(last_safety_level=-1, last_safety_at=0.0, now=100.0))

    def test_stale_message_fails_toward_caution(self):
        self.assertTrue(
            self.derive(last_safety_level=1, last_safety_at=0.0, now=10.0)  # NORMAL, but 10s stale
        )

    def test_fresh_normal_state_is_not_caution(self):
        self.assertFalse(self.derive(last_safety_level=1, last_safety_at=99.0, now=100.0))

    def test_fresh_caution_state_is_caution(self):
        self.assertTrue(self.derive(last_safety_level=self.CAUTION, last_safety_at=99.0, now=100.0))

    def test_fresh_danger_state_is_caution_or_above(self):
        self.assertTrue(self.derive(last_safety_level=3, last_safety_at=99.0, now=100.0))


if __name__ == "__main__":
    unittest.main()
