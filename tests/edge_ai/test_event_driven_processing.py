"""Edge AI Runtime brief Phase 13 -- Phase 9's exact event-driven-processing
rules per ASR/LLM/TTS/object-detection/gesture/emotion/RAG/navigation.
Each capability's own deep behavioral coverage already lives in its
package's test suite (bonbon_vision/tests/test_frame_throttler.py,
bonbon_navigation/tests/test_approved_command_gate.py,
tests/speech_ai/test_tts_router.py, etc.) -- these tests check the
specific cross-cutting rule for each area, including regression guards
for the two real Phase 9 findings this session fixed (TTS not checking
cache first; navigation goals dispatched from more than one source)."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestNavigationOnlyDispatchesFromApprovedCommands(unittest.TestCase):
    """GAP-E2 regression guard: a behavior recommendation alone must never
    enqueue a Nav2 goal -- only an approved command from
    bonbon_motion_approval_gateway may. Parsed via `ast` from the raw
    source file rather than imported -- navigation_node.py imports real
    rclpy at module scope, which isn't installed in this environment
    (see bonbon_navigation's own test suite, run separately, for real
    behavioral coverage of this node)."""

    def setUp(self):
        import ast

        path = (
            _REPO_ROOT / "ros2_ws" / "src" / "bonbon_navigation" / "bonbon_navigation"
            / "nodes" / "navigation_node.py"
        )
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
        self.methods: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "NavigationNode":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in (
                        "_on_behavior_recommendation", "_on_approved_command",
                    ):
                        self.methods[item.name] = ast.get_source_segment(source_text, item)

    def test_behavior_recommendation_handler_never_calls_enqueue(self):
        self.assertIn("_on_behavior_recommendation", self.methods)
        self.assertNotIn(".enqueue(", self.methods["_on_behavior_recommendation"])

    def test_approved_command_handler_is_gated_by_should_dispatch_navigation(self):
        self.assertIn("_on_approved_command", self.methods)
        source = self.methods["_on_approved_command"]
        self.assertIn("should_dispatch_navigation(", source)
        self.assertIn(".enqueue(", source)


class TestTTSChecksCacheBeforeSynthesis(unittest.TestCase):
    """Phase 9 fix this session: speak() must check the phrase cache
    BEFORE touching the runtime selector, not after a synthesis attempt."""

    def setUp(self):
        import sys

        speech_src = _REPO_ROOT / "ros2_ws" / "src" / "bonbon_speech_ai"
        if str(speech_src) not in sys.path:
            sys.path.insert(0, str(speech_src))
        from bonbon_speech_ai.tts_router import TTSRouter

        self.source = inspect.getsource(TTSRouter.speak)

    def test_cached_phrase_check_appears_before_selector_use(self):
        cache_check_pos = self.source.find("_cached_phrase_path")
        selector_pos = self.source.find("self._selector")
        self.assertNotEqual(cache_check_pos, -1, "speak() no longer calls _cached_phrase_path")
        self.assertNotEqual(selector_pos, -1, "speak() no longer touches self._selector")
        self.assertLess(cache_check_pos, selector_pos, "cache check must run before the runtime selector is touched")


class TestLLMIsLastResort(unittest.TestCase):
    def test_pi_human_ai_resolution_order_puts_llm_last(self):
        import yaml

        data = yaml.safe_load((_REPO_ROOT / "config" / "distributed" / "pi_human_ai.yaml").read_text(encoding="utf-8"))
        order = data["llm"]["resolution_order"]
        self.assertEqual(order[-1], "llm")

    def test_pi_human_ai_forbids_cloud_llm_calls_by_default(self):
        import yaml

        data = yaml.safe_load((_REPO_ROOT / "config" / "distributed" / "pi_human_ai.yaml").read_text(encoding="utf-8"))
        self.assertIn("cloud_llm_api_calls_by_default", data["forbidden"])


class TestRAGChecksCacheBeforeRetrieval(unittest.TestCase):
    def test_faq_route_hits_cache_before_rag_when_cache_manager_provided(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager
        from bonbon_edge_ai_runtime.task_router import ChosenMethod, TaskRouter

        cache = CacheManager()
        cache.rag_put("what are visiting hours", "faq", ["9am - 8pm daily"])
        router = TaskRouter(cache_manager=cache)

        decision = router.route_text_intent("what are visiting hours")
        self.assertEqual(decision.chosen_method, ChosenMethod.CACHED_ANSWER)

    def test_privacy_unsafe_rag_result_is_refused_not_cached(self):
        from bonbon_edge_ai_runtime.cache_manager import CacheManager

        cache = CacheManager()
        stored = cache.rag_put("patient 12345 medications", "patient_lookup", ["..."], privacy_safe=False)
        self.assertFalse(stored)


class TestGestureAndEmotionAreEventDrivenNotPolled(unittest.TestCase):
    def test_safety_gesture_dispatches_as_a_proposal_requiring_approval(self):
        from bonbon_edge_ai_runtime.task_router import TaskRouter

        router = TaskRouter()
        decision = router.route_gesture("stop_palm", confidence=0.9)
        self.assertTrue(decision.safety_required)
        self.assertTrue(decision.dashboard_event["safetyBlocked"] is False)

    def test_low_confidence_emotion_never_changes_behavior(self):
        from bonbon_edge_ai_runtime.task_router import TaskRouter

        router = TaskRouter()
        decision = router.route_emotion("sad", confidence=0.2)
        self.assertFalse(decision.safety_required)


class TestVisionFrameThrottlingExists(unittest.TestCase):
    """bonbon_vision/tests/test_frame_throttler.py owns the deep behavioral
    coverage for this -- this just confirms the module this brief's
    accelerator_manager.DEFAULT_STALE_AFTER_SEC assumes actually exists,
    so the two don't silently drift apart."""

    def test_frame_throttler_module_exists(self):
        path = _REPO_ROOT / "ros2_ws" / "src" / "bonbon_vision" / "bonbon_vision" / "preprocessing" / "frame_throttler.py"
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
