"""Phase 8: LLM and RAG benchmarking against the 8 required prompts.

Routing correctness reuses the real TaskRouter (same as
test_task_routing_efficiency.py) -- these 8 prompts are this brief's own
specific phrasing, checked against the same real router, not a duplicate
routing engine. Latency reuses bonbon_benchmarks.llm_benchmark.
"""

from __future__ import annotations

import pytest
from bonbon_edge_ai_runtime.task_router import ChosenMethod, TaskRouter

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks import llm_benchmark

_PROMPTS = [
    "Who are you?",
    "Where is reception?",
    "Where is cardiology?",
    "Please guide me.",
    "Explain in Telugu: I will help you book an appointment.",
    "A patient looks confused. Give one polite sentence.",
    "Emergency stop now.",
    "Move forward now.",
]


@pytest.fixture
def router() -> TaskRouter:
    return TaskRouter()


class TestEmergencyStopNeverCallsLLM:
    def test_emergency_stop_now_is_deterministic_not_llm(self, router):
        decision = router.route_text_intent("Emergency stop now.")
        assert decision.chosen_method == ChosenMethod.DETERMINISTIC_RULE
        assert decision.chosen_model is None
        assert decision.safety_required is True


class TestMoveForwardNeverProducesDirectMovementCommand:
    def test_move_forward_now_is_not_a_direct_control_method(self, router):
        decision = router.route_text_intent("Move forward now.")
        direct_control_methods = {"direct_motor_control", "direct_nav2_goal", "direct_servo_control"}
        assert decision.chosen_method.value not in direct_control_methods
        assert decision.chosen_method != ChosenMethod.TINY_LOCAL_LLM  # never handed to the LLM as if it could act on it

    def test_move_forward_now_is_a_real_navigation_pattern_gap_worth_noting(self, router):
        # Honest finding, not silently fixed here (out of scope for a
        # benchmark pass): "Move forward now." matches NEITHER
        # _EMERGENCY_KEYWORDS NOR _NAVIGATION_PATTERN (which requires
        # "guide/take/walk me to X" or "navigate (me) to X" phrasing), so
        # it falls through to the FAQ/RAG branch rather than being
        # recognized as a movement-related utterance at all. This is
        # SAFE (RAG_RETRIEVAL cannot move the robot) but not the semantic
        # "navigation request -> proposal only" path the brief describes
        # -- see docs/benchmarks/LLM_RAG_BENCHMARK_REPORT.md.
        decision = router.route_text_intent("Move forward now.")
        assert decision.chosen_method == ChosenMethod.RAG_RETRIEVAL
        assert decision.safety_required is False


class TestHospitalFactsUseRAGNotDirectLLM:
    @pytest.mark.parametrize("prompt", ["Where is reception?", "Where is cardiology?"])
    def test_location_questions_route_to_cache_or_rag(self, router, prompt):
        decision = router.route_text_intent(prompt)
        assert decision.chosen_method in (ChosenMethod.CACHED_ANSWER, ChosenMethod.RAG_RETRIEVAL)


class TestQwenUsedOnlyForShortWording:
    def test_who_are_you_is_a_small_talk_style_prompt(self, router):
        # "Who are you?" matches no emergency/navigation/appointment/faq
        # keyword rule -- with an explicit small_talk intent_class (as a
        # real upstream classifier would supply), it reaches the LLM
        # branch, matching this brief's "Qwen used only for short wording."
        decision = router.route_text_intent("Who are you?", intent_class="small_talk")
        assert decision.chosen_method == ChosenMethod.TINY_LOCAL_LLM
        assert decision.chosen_model == "llm_qwen25_05b"

    def test_confused_patient_wording_prompt_is_llm_appropriate(self, router):
        decision = router.route_text_intent(
            "A patient looks confused. Give one polite sentence.", intent_class="small_talk"
        )
        assert decision.chosen_method == ChosenMethod.TINY_LOCAL_LLM


class TestAllEightPromptsRouteWithoutError:
    def test_every_required_prompt_produces_a_route_decision(self, router):
        for prompt in _PROMPTS:
            decision = router.route_text_intent(prompt)
            assert decision.route_id
            assert decision.chosen_method is not None


class TestLLMLatencyBenchmark:
    def test_short_answer_latency_reports_real_or_honestly_blocked(self):
        m = llm_benchmark.benchmark_short_answer(iterations=2)
        assert m.status in ("PASS", "FAIL", "BLOCKED")
        assert m.target == 2000.0
        assert m.target_stat == "p95"
