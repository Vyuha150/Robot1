"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.task_router.
Exercises the 8 exact routing examples Phase 4 of the brief names, plus
the required RouteDecision output-field contract (route_id, task_type,
chosen_method, chosen_model, fallback_model, reason, confidence,
estimated_latency, safety_required, dashboard_event)."""

from __future__ import annotations

import unittest


class TestRouteDecisionFieldContract(unittest.TestCase):
    def setUp(self):
        from bonbon_edge_ai_runtime.task_router import TaskRouter

        self.router = TaskRouter()

    def test_every_route_decision_has_all_required_fields(self):
        decision = self.router.route_text_intent("hello there")
        as_dict = decision.to_dict()
        for field in (
            "routeId", "taskType", "chosenMethod", "chosenModel", "fallbackModel",
            "reason", "confidence", "estimatedLatencyMs", "safetyRequired", "dashboardEvent",
        ):
            self.assertIn(field, as_dict, f"RouteDecision.to_dict() is missing required field {field!r}")


class TestPhase4RoutingExamples(unittest.TestCase):
    """The 8 exact routing examples named in the brief."""

    def setUp(self):
        from bonbon_edge_ai_runtime.task_router import ChosenMethod, TaskRouter

        self.router = TaskRouter()
        self.ChosenMethod = ChosenMethod

    def test_emergency_phrase_routes_to_deterministic_rule_and_is_safety_required(self):
        decision = self.router.route_text_intent("help, someone collapsed")
        self.assertEqual(decision.chosen_method, self.ChosenMethod.DETERMINISTIC_RULE)
        self.assertEqual(decision.task_type, "emergency")
        self.assertTrue(decision.safety_required)
        self.assertIsNone(decision.chosen_model)  # no LLM involved

    def test_where_is_cardiology_routes_to_faq_not_navigation(self):
        decision = self.router.route_text_intent("Where is Cardiology?")
        self.assertEqual(decision.task_type, "faq")
        self.assertIn(decision.chosen_method, (self.ChosenMethod.CACHED_ANSWER, self.ChosenMethod.RAG_RETRIEVAL))

    def test_book_appointment_with_dr_rao_routes_to_deterministic_workflow(self):
        decision = self.router.route_text_intent("Book appointment with Dr. Rao")
        self.assertEqual(decision.task_type, "appointment")
        self.assertEqual(decision.chosen_method, self.ChosenMethod.DETERMINISTIC_RULE)
        self.assertFalse(decision.safety_required)

    def test_guide_me_to_room_203_routes_to_navigation_and_requires_safety_approval(self):
        decision = self.router.route_text_intent("Guide me to room 203")
        self.assertEqual(decision.task_type, "navigation")
        self.assertTrue(decision.safety_required)
        self.assertEqual(decision.dashboard_event["safetyCategory"], "NAVIGATION_REQUEST")

    def test_general_small_talk_routes_to_tiny_local_llm(self):
        # Any text intent NOT classified as faq/hospital_info (or None,
        # which itself defaults to the FAQ/RAG path) falls through to
        # small_talk -- upstream intent classification is what actually
        # produces this label; simulate that here.
        decision = self.router.route_text_intent("what's your favorite color", intent_class="small_talk")
        self.assertEqual(decision.task_type, "small_talk")
        self.assertEqual(decision.chosen_method, self.ChosenMethod.TINY_LOCAL_LLM)
        self.assertEqual(decision.chosen_model, "llm_qwen25_05b")

    def test_stop_palm_gesture_routes_as_safety_relevant_proposal(self):
        decision = self.router.route_gesture("stop_palm", confidence=0.9)
        self.assertEqual(decision.task_type, "gesture_safety")
        self.assertTrue(decision.safety_required)
        self.assertEqual(decision.dashboard_event["safetyCategory"], "ACTUATION_REQUEST")

    def test_unknown_gesture_routes_to_degraded_fallback_and_takes_no_action(self):
        decision = self.router.route_gesture("cartwheel", confidence=0.9)
        self.assertEqual(decision.task_type, "gesture_unknown")
        self.assertEqual(decision.chosen_method, self.ChosenMethod.DEGRADED_FALLBACK_TEMPLATE)
        self.assertFalse(decision.safety_required)

    def test_low_confidence_emotion_is_not_actionable(self):
        decision = self.router.route_emotion("angry", confidence=0.3)
        self.assertFalse(decision.safety_required)
        self.assertIn("uncertain evidence", decision.reason)


class TestTaskRouterUsesCacheWhenProvided(unittest.TestCase):
    def test_faq_cache_hit_skips_rag(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager
        from bonbon_edge_ai_runtime.task_router import ChosenMethod, TaskRouter

        cache = CacheManager()
        cache.rag_put("where is radiology", "faq", ["Radiology is on the 2nd floor"])
        router = TaskRouter(cache_manager=cache)

        decision = router.route_text_intent("where is radiology")
        self.assertEqual(decision.chosen_method, ChosenMethod.CACHED_ANSWER)


if __name__ == "__main__":
    unittest.main()
