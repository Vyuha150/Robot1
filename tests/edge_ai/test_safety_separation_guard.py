"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.safety_separation_guard.
Covers the 9 action categories, the brief's explicit "never allow" table
(LLM/UI/AI-Pi -> direct motor/servo/nav2-goal/emergency-override), and
dashboard visibility of blocked actions (Phase 7 requirement 8)."""

from __future__ import annotations

import unittest


class TestNineActionCategories(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.safety_separation_guard import ActionCategory, SafetySeparationGuard

        self.guard = SafetySeparationGuard()
        self.ActionCategory = ActionCategory

    def test_nine_categories_exist(self):
        names = {c.value for c in self.ActionCategory}
        self.assertEqual(
            names,
            {
                "TEXT_ONLY", "INFO_LOOKUP", "STAFF_ALERT", "NAVIGATION_REQUEST",
                "ACTUATION_REQUEST", "SAFETY_CRITICAL", "UNSAFE_DIRECT_CONTROL",
                "MEDICAL_DIAGNOSIS_RISK", "PRIVACY_RISK",
            },
        )

    def test_text_response_classified_text_only_and_allowed(self):
        result = self.guard.classify("llm", "text_response", {"text": "the cafeteria is on floor 1"})
        self.assertEqual(result.category, self.ActionCategory.TEXT_ONLY)
        self.assertFalse(result.blocked)

    def test_navigation_request_requires_approval_but_is_not_blocked(self):
        result = self.guard.classify("behavior_engine", "navigation_request", {})
        self.assertEqual(result.category, self.ActionCategory.NAVIGATION_REQUEST)
        self.assertFalse(result.blocked)
        self.assertTrue(result.requires_approval)

    def test_diagnosis_sounding_text_is_blocked(self):
        result = self.guard.classify("llm", "text_response", {"text": "you have a fractured wrist"})
        self.assertEqual(result.category, self.ActionCategory.MEDICAL_DIAGNOSIS_RISK)
        self.assertTrue(result.blocked)

    def test_privacy_field_in_payload_is_blocked(self):
        result = self.guard.classify("ai_pi_speech", "text_response", {"text": "ok", "patient_medical_record": "..."})
        self.assertEqual(result.category, self.ActionCategory.PRIVACY_RISK)
        self.assertTrue(result.blocked)

    def test_unrecognized_action_type_fails_closed_not_default_allow(self):
        result = self.guard.classify("mystery_module", "do_something_new", {})
        self.assertTrue(result.blocked)
        self.assertEqual(result.category, self.ActionCategory.UNSAFE_DIRECT_CONTROL)


class TestNeverAllowTable(unittest.TestCase):
    """The brief's explicit table: LLM, UI, and AI-Pi perception/gesture
    must never reach direct_motor_command, direct_servo_command,
    raw_nav2_goal, or emergency_override -- only the Navigation Pi's
    own safety authority may."""

    def setUp(self):
        from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

        self.guard = SafetySeparationGuard()

    def test_llm_direct_motor_command_blocked(self):
        result = self.guard.classify("llm", "direct_motor_command", {})
        self.assertTrue(result.blocked)

    def test_llm_direct_servo_command_blocked(self):
        result = self.guard.classify("llm", "direct_servo_command", {})
        self.assertTrue(result.blocked)

    def test_ui_raw_nav2_goal_blocked(self):
        result = self.guard.classify("ui", "raw_nav2_goal", {})
        self.assertTrue(result.blocked)

    def test_ui_emergency_override_blocked(self):
        result = self.guard.classify("ui", "emergency_override", {})
        self.assertTrue(result.blocked)

    def test_ai_pi_gesture_direct_motor_command_blocked(self):
        result = self.guard.classify("ai_pi_gesture", "direct_motor_command", {})
        self.assertTrue(result.blocked)

    def test_ai_pi_perception_raw_nav2_goal_blocked(self):
        result = self.guard.classify("ai_pi_perception", "raw_nav2_goal", {})
        self.assertTrue(result.blocked)

    def test_authorized_safety_authority_direct_control_is_allowed(self):
        result = self.guard.classify("safety_supervisor", "direct_motor_command", {})
        self.assertFalse(result.blocked)


class TestBlockedActionDashboardVisibility(unittest.TestCase):
    def test_blocked_actions_appear_in_summary_and_count(self):
        from bonbon_edge_ai_runtime.safety_separation_guard import SafetySeparationGuard

        guard = SafetySeparationGuard()
        guard.classify("llm", "direct_motor_command", {})
        guard.classify("ui", "raw_nav2_goal", {})
        guard.classify("behavior_engine", "text_response", {"text": "hello"})  # not blocked

        summary = guard.summary()
        self.assertEqual(summary["totalClassified"], 3)
        self.assertEqual(summary["totalBlocked"], 2)
        self.assertEqual(len(summary["recentBlocked"]), 2)
        sources = {b["sourceModule"] for b in summary["recentBlocked"]}
        self.assertEqual(sources, {"llm", "ui"})


if __name__ == "__main__":
    unittest.main()
