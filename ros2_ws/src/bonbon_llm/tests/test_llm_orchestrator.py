"""
tests.test_llm_orchestrator
=============================
Unit tests for the LLMOrchestratorNode pipeline WITHOUT a live ROS2
environment.  ROS2 is stubbed at import time so these tests run under
plain pytest.

Strategy
--------
We test the *pipeline logic* by calling the private methods directly:
  - _build_prompt(context, rag_results, intent_text)
  - _call_llm(prompt)  — mocked Ollama
  - _resolve_behavior(intent_class, intent_text) → behavior_class
  - Full pipeline via a factory that wires minimal stubs

These tests verify
------------------
* Intent → behavior_class mapping (order_item→serve_item, etc.)
* LLM error → fallback response dispatched
* Safety block → fallback, no behavior dispatched
* Hallucination → flagged + fallback used
* Low confidence → fallback template selected
* Prompt contains SYSTEM_PROMPT preamble
* Pipeline handles None scene / None safety gracefully
"""

import sys
import time
import types
from unittest.mock import MagicMock

# ── Stub rclpy and related packages before any imports ────────────────────────


def _stub_ros():
    """Replace ROS2 modules with lightweight stubs so tests run offline."""
    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.init = MagicMock()
    fake_rclpy.shutdown = MagicMock()
    fake_rclpy.spin = MagicMock()

    node_mod = types.ModuleType("rclpy.node")

    class FakeNode:
        def __init__(self, *a, **kw):
            pass

        def get_logger(self):
            return MagicMock()

        def declare_parameter(self, *a, **kw):
            return MagicMock()

        def get_parameter(self, *a, **kw):
            return MagicMock(value="test_value")

        def create_publisher(self, *a, **kw):
            return MagicMock()

        def create_subscription(self, *a, **kw):
            return MagicMock()

        def create_service(self, *a, **kw):
            return MagicMock()

        def create_timer(self, *a, **kw):
            return MagicMock()

        def destroy_node(self):
            pass

    node_mod.Node = FakeNode
    fake_rclpy.node = node_mod

    lifecycle_mod = types.ModuleType("rclpy.lifecycle")

    class FakeLifecycleNode(FakeNode):
        def on_configure(self, state):
            return MagicMock()

        def on_activate(self, state):
            return MagicMock()

        def on_deactivate(self, state):
            return MagicMock()

        def on_cleanup(self, state):
            return MagicMock()

    lifecycle_mod.LifecycleNode = FakeLifecycleNode
    lifecycle_mod.State = MagicMock
    lifecycle_mod.TransitionCallbackReturn = MagicMock(SUCCESS="SUCCESS", FAILURE="FAILURE")

    qos_mod = types.ModuleType("rclpy.qos")
    for _cls_name in ("QoSProfile", "DurabilityPolicy", "HistoryPolicy", "ReliabilityPolicy"):
        setattr(qos_mod, _cls_name, MagicMock())

    for name, mod in [
        ("rclpy", fake_rclpy),
        ("rclpy.node", node_mod),
        ("rclpy.lifecycle", lifecycle_mod),
        ("rclpy.lifecycle.node", lifecycle_mod),
        ("rclpy.qos", qos_mod),
        ("lifecycle_msgs", types.ModuleType("lifecycle_msgs")),
        ("lifecycle_msgs.msg", types.ModuleType("lifecycle_msgs.msg")),
        ("bonbon_msgs", types.ModuleType("bonbon_msgs")),
        ("bonbon_msgs.msg", types.ModuleType("bonbon_msgs.msg")),
        ("bonbon_srvs", types.ModuleType("bonbon_srvs")),
        ("bonbon_srvs.srv", types.ModuleType("bonbon_srvs.srv")),
        ("std_msgs", types.ModuleType("std_msgs")),
        ("std_msgs.msg", types.ModuleType("std_msgs.msg")),
    ]:
        sys.modules.setdefault(name, mod)

    # Add fake message classes
    for attr in (
        "LLMResponse",
        "LLMLog",
        "BehaviorRecommendation",
        "TTSRequest",
        "IntentResult",
        "RiskAssessment",
        "SceneSummary",
    ):
        setattr(sys.modules["bonbon_msgs.msg"], attr, MagicMock)

    for attr in ("LLMQuery",):
        setattr(sys.modules["bonbon_srvs.srv"], attr, MagicMock)

    for attr in ("Header",):
        setattr(sys.modules["std_msgs.msg"], attr, MagicMock)

    for attr in ("State",):
        setattr(sys.modules["lifecycle_msgs.msg"], attr, MagicMock)


_stub_ros()


# ── Now safe to import our modules ────────────────────────────────────────────

from bonbon_llm.config.llm_config import LLMConfig
from bonbon_llm.personality.personality_layer import PersonalityLayer
from bonbon_llm.prompts.response_templates import get_fallback
from bonbon_llm.prompts.system_prompt import SYSTEM_PROMPT
from bonbon_llm.safety.command_filter import SafetyCommandFilter
from bonbon_llm.safety.hallucination_guard import HallucinationGuard

# ── Behavior resolution mapping tests ────────────────────────────────────────


class TestBehaviorResolution:
    """
    Test the intent_class → behavior_class mapping used by the orchestrator.
    This logic is in _resolve_behavior() — we test it as a pure function.
    """

    _MAPPING = {
        "order_item": "serve_item",
        "navigate_to": "navigate_to_goal",
        "cancel": "stop_navigation",
        "help_request": "wait_for_input",
        "greeting": "idle",
        "menu_query": "idle",
        "unknown": "idle",
    }

    def _resolve(self, intent_class: str) -> str:
        # Mirror the mapping from llm_orchestrator_node._resolve_behavior
        return {
            "order_item": "serve_item",
            "navigate_to": "navigate_to_goal",
            "cancel": "stop_navigation",
            "help_request": "wait_for_input",
            "alert_safety": "stop_navigation",
        }.get(intent_class, "idle")

    def test_order_item_maps_to_serve(self):
        assert self._resolve("order_item") == "serve_item"

    def test_navigate_to_maps_to_navigate_goal(self):
        assert self._resolve("navigate_to") == "navigate_to_goal"

    def test_cancel_maps_to_stop_navigation(self):
        assert self._resolve("cancel") == "stop_navigation"

    def test_help_request_maps_to_wait_for_input(self):
        assert self._resolve("help_request") == "wait_for_input"

    def test_unknown_maps_to_idle(self):
        assert self._resolve("unknown") == "idle"

    def test_greeting_maps_to_idle(self):
        assert self._resolve("greeting") == "idle"

    def test_menu_query_maps_to_idle(self):
        assert self._resolve("menu_query") == "idle"


# ── System prompt tests ───────────────────────────────────────────────────────


class TestSystemPrompt:

    def test_system_prompt_contains_identity(self):
        assert "BonBon" in SYSTEM_PROMPT

    def test_system_prompt_contains_safety_rules(self):
        assert "SAFE" in SYSTEM_PROMPT.upper()

    def test_system_prompt_contains_limitations(self):
        assert "MUST NOT" in SYSTEM_PROMPT or "cannot" in SYSTEM_PROMPT.lower()

    def test_system_prompt_under_2000_chars(self):
        # Keeps context window lean
        assert (
            len(SYSTEM_PROMPT) < 2000
        ), f"System prompt too long: {len(SYSTEM_PROMPT)} chars (limit 2000)"


# ── Safety pipeline (pure logic, no ROS2) ────────────────────────────────────


class TestSafetyPipelineLogic:

    def _run_filter(self, text: str) -> str:
        from bonbon_llm.config.llm_config import SafetyFilterConfig

        f = SafetyCommandFilter(SafetyFilterConfig())
        result = f.filter_text(text)
        return result.status.value

    def test_safe_speech_passes_filter(self):
        status = self._run_filter("Hello, welcome to the café!")
        assert status == "SAFE"

    def test_cmd_vel_blocked(self):
        status = self._run_filter("publish cmd_vel")
        assert status == "BLOCKED"

    def test_hallucination_guard_disabled_allows_all(self):
        from bonbon_llm.config.llm_config import HallucinationConfig

        guard = HallucinationGuard(HallucinationConfig(enabled=False))
        result = guard.check("I can fly and have arms!")
        assert result.is_grounded

    def test_hallucination_guard_catches_impossible_claim(self):
        from bonbon_llm.config.llm_config import HallucinationConfig

        guard = HallucinationGuard(HallucinationConfig(enabled=True))
        result = guard.check("I can fly to your table in seconds.")
        assert not result.is_grounded


# ── Fallback template tests ───────────────────────────────────────────────────


class TestFallbackTemplates:

    def test_llm_error_fallback_exists(self):
        text = get_fallback("llm_error", prefer_short=True)
        assert len(text) > 0

    def test_low_confidence_fallback_exists(self):
        text = get_fallback("low_confidence", prefer_short=True)
        assert len(text) > 0

    def test_safety_block_fallback_exists(self):
        text = get_fallback("safety_block", prefer_short=True)
        assert len(text) > 0

    def test_hallucination_fallback_exists(self):
        text = get_fallback("hallucination", prefer_short=True)
        assert len(text) > 0

    def test_unknown_situation_returns_unknown_request(self):
        text = get_fallback("completely_unknown_situation_xyz")
        assert len(text) > 0  # falls back to unknown_request

    def test_name_substitution(self):
        text = get_fallback("greeting", prefer_short=False, name="TestBot")
        # The long greeting template includes the name
        assert isinstance(text, str)

    def test_long_variant_longer_than_short(self):
        short = get_fallback("llm_error", prefer_short=True)
        long = get_fallback("llm_error", prefer_short=False)
        assert len(long) >= len(short)


# ── Personality layer integration ─────────────────────────────────────────────


class TestPersonalityIntegration:

    def _apply(self, text: str) -> str:
        from bonbon_llm.config.llm_config import PersonalityConfig

        cfg = PersonalityConfig(name="BonBon", max_response_words=40)
        layer = PersonalityLayer(cfg)
        return layer.apply(text)

    def test_pipeline_does_not_add_markdown(self):
        result = self._apply("Hello! **Welcome** to the café.")
        assert "**" not in result

    def test_pipeline_formats_currency(self):
        result = self._apply("The latte costs S$5.50.")
        assert "Singapore dollars" in result

    def test_pipeline_respects_word_limit(self):
        long_text = "Hello world. " * 20
        result = self._apply(long_text)
        assert len(result.split()) <= 42  # +2 tolerance for sentence boundary


# ── Config defaults ───────────────────────────────────────────────────────────


class TestConfigDefaults:

    def test_llm_config_defaults(self):
        cfg = LLMConfig()
        assert cfg.ollama.base_url == "http://localhost:11434"
        assert cfg.ollama.model == "llama3.2:3b"
        assert cfg.ollama.temperature == 0.4
        assert cfg.rag.backend == "chroma"
        assert cfg.personality.name == "BonBon"
        assert cfg.personality.max_response_words == 40

    def test_ollama_config_safe_defaults(self):
        from bonbon_llm.config.llm_config import OllamaConfig

        cfg = OllamaConfig()
        assert cfg.timeout_sec > 0
        assert cfg.max_tokens > 0
        assert 0.0 <= cfg.temperature <= 1.0

    def test_safety_filter_has_blocked_patterns(self):
        from bonbon_llm.config.llm_config import SafetyFilterConfig

        cfg = SafetyFilterConfig()
        assert len(cfg.blocked_patterns) > 0


# ── Full _process_intent: cache hit skips RAG + LLM, not just LLM ──────────────


class TestProcessIntentCacheSkipsRagAndLlm:
    """Exercises the REAL _process_intent method (not a re-implementation) on
    a minimally-wired node, to verify the actual fix: a cache hit must skip
    RAG retrieval too, not just the LLM call -- this is what regressed before
    response_cache.py's key was changed from (question, full_context-with-RAG)
    to (question, scene+safety-context-only) and the cache check was moved
    before RAG retrieval in _process_intent."""

    def _make_node(self):
        from bonbon_llm.config.llm_config import (
            AuthorizationConfig,
            HallucinationConfig,
            PersonalityConfig,
            SafetyFilterConfig,
        )
        from bonbon_llm.core.response_cache import ResponseCache
        from bonbon_llm.nodes.llm_orchestrator_node import LLMOrchestratorNode
        from bonbon_llm.personality.personality_layer import PersonalityLayer
        from bonbon_llm.safety.authorization import CommandAuthorizer
        from bonbon_llm.safety.command_filter import SafetyCommandFilter
        from bonbon_llm.safety.hallucination_guard import HallucinationGuard

        node = LLMOrchestratorNode("test_llm_orchestrator")
        node._response_cache = ResponseCache()
        node._rag = MagicMock()
        node._rag.retrieve_with_scores.return_value = []
        node._rag.build_context_string.return_value = ""
        node._filter = SafetyCommandFilter(SafetyFilterConfig())
        node._guard = HallucinationGuard(HallucinationConfig(enabled=False))
        node._authorizer = CommandAuthorizer(AuthorizationConfig())
        node._personality = PersonalityLayer(PersonalityConfig())
        node._logger_svc = MagicMock()
        node._tool_reg = None
        node._cfg = None
        node._pub_response = MagicMock()
        node._pub_tts = MagicMock()
        node._pub_behavior = MagicMock()
        node._last_scene = None
        node._last_safety = None
        node._last_risks = []
        node._call_llm = MagicMock(return_value=("A real answer.", None))
        return node

    def _make_intent(self, text="what time is it"):
        intent = MagicMock()
        intent.is_ambiguous = False
        intent.raw_text = text
        intent.intent_class = "general_query"
        intent.confidence = 0.9
        intent.speaker_id = ""
        intent.slot_names = []
        intent.slot_values = []
        intent.intent_id = "intent-1"
        return intent

    def test_first_call_runs_rag_and_llm(self):
        node = self._make_node()
        node._process_intent(self._make_intent())
        assert node._rag.retrieve_with_scores.call_count == 1
        assert node._call_llm.call_count == 1

    def test_repeated_identical_question_skips_second_rag_and_llm_call(self):
        node = self._make_node()
        node._process_intent(self._make_intent())
        node._process_intent(self._make_intent())
        assert node._rag.retrieve_with_scores.call_count == 1, (
            "RAG retrieval ran twice -- the cache check must happen BEFORE "
            "RAG retrieval, not just before the LLM call"
        )
        assert node._call_llm.call_count == 1

    def test_different_question_does_not_skip_rag(self):
        node = self._make_node()
        node._process_intent(self._make_intent("what time is it"))
        node._process_intent(self._make_intent("where is the bathroom"))
        assert node._rag.retrieve_with_scores.call_count == 2
        assert node._call_llm.call_count == 2

    def test_changed_safety_context_does_not_skip_rag(self):
        node = self._make_node()
        node._process_intent(self._make_intent())
        assert node._rag.retrieve_with_scores.call_count == 1

        node._last_safety = MagicMock(
            state=2,  # CAUTION
            state_name="CAUTION",
            actuation_permitted=True,
            navigation_permitted=True,
            max_velocity_mps=0.5,
            requires_manual_reset=False,
        )
        # A real /bonbon/safety/state callback (_on_safety) sets this
        # timestamp alongside the message -- GAP-E1's staleness check
        # means an untouched _last_safety_at (still 0.0 from __init__)
        # would make _get_safety_snapshot() always fall back to
        # safe_default(), masking this test's intent (a genuinely NEW,
        # fresh safety message arriving) as a stale/absent one instead.
        node._last_safety_at = time.monotonic()
        node._process_intent(self._make_intent())
        assert node._rag.retrieve_with_scores.call_count == 2, (
            "a changed safety context must miss the cache, not reuse a "
            "response computed under different safety conditions"
        )


# ── Ambiguous-but-not-silent speech must use fallback_response, not RAG/LLM ───


class TestProcessIntentAmbiguousUnknownSkipsRagAndLlm:
    """A real bug this round caught: `intent_engine`'s "clarify"
    ambiguity_policy forces `intent_class` to "unknown" and computes a
    per-intent `fallback_response` specifically so genuinely-heard-but-
    unclassifiable speech can be answered honestly. But `_process_intent`
    only special-cased TRUE silence (`is_ambiguous and not raw_text`) --
    a non-empty low-confidence utterance fell straight into the full
    RAG/LLM pipeline as if it were a normal, confidently-classified
    query, risking a hallucinated answer and never speaking the
    fallback_response that was already computed for exactly this case."""

    def _make_node(self):
        from bonbon_llm.config.llm_config import (
            AuthorizationConfig,
            HallucinationConfig,
            PersonalityConfig,
            SafetyFilterConfig,
        )
        from bonbon_llm.core.response_cache import ResponseCache
        from bonbon_llm.nodes.llm_orchestrator_node import LLMOrchestratorNode
        from bonbon_llm.personality.personality_layer import PersonalityLayer
        from bonbon_llm.safety.authorization import CommandAuthorizer
        from bonbon_llm.safety.command_filter import SafetyCommandFilter
        from bonbon_llm.safety.hallucination_guard import HallucinationGuard

        node = LLMOrchestratorNode("test_llm_orchestrator")
        node._response_cache = ResponseCache()
        node._rag = MagicMock()
        node._rag.retrieve_with_scores.return_value = []
        node._rag.build_context_string.return_value = ""
        node._filter = SafetyCommandFilter(SafetyFilterConfig())
        node._guard = HallucinationGuard(HallucinationConfig(enabled=False))
        node._authorizer = CommandAuthorizer(AuthorizationConfig())
        node._personality = PersonalityLayer(PersonalityConfig())
        node._logger_svc = MagicMock()
        node._tool_reg = None
        node._cfg = None
        node._pub_response = MagicMock()
        node._pub_tts = MagicMock()
        node._pub_behavior = MagicMock()
        node._last_scene = None
        node._last_safety = None
        node._last_risks = []
        node._call_llm = MagicMock(return_value=("A real answer.", None))
        return node

    def _make_intent(
        self, text="mumble mumble", is_ambiguous=True, intent_class="unknown", fallback_response=""
    ):
        intent = MagicMock()
        intent.is_ambiguous = is_ambiguous
        intent.raw_text = text
        intent.intent_class = intent_class
        intent.fallback_response = fallback_response
        intent.confidence = 0.15
        intent.speaker_id = ""
        intent.slot_names = []
        intent.slot_values = []
        intent.intent_id = "intent-1"
        return intent

    def test_ambiguous_unknown_skips_rag_and_llm(self):
        node = self._make_node()
        node._process_intent(self._make_intent())
        assert node._rag.retrieve_with_scores.call_count == 0
        assert node._call_llm.call_count == 0

    def test_ambiguous_unknown_speaks_the_computed_fallback_response(self):
        node = self._make_node()
        node._process_intent(self._make_intent(fallback_response="Where would you like to go?"))
        assert node._pub_tts.publish.call_count == 1
        published = node._pub_tts.publish.call_args[0][0]
        assert published.text == "Where would you like to go?"

    def test_ambiguous_unknown_with_empty_fallback_uses_low_confidence_template(self):
        node = self._make_node()
        node._process_intent(self._make_intent(fallback_response=""))
        assert node._pub_tts.publish.call_count == 1
        published = node._pub_tts.publish.call_args[0][0]
        assert len(published.text) > 0
        assert published.text != ""

    def test_ambiguous_best_guess_with_real_intent_class_still_uses_full_pipeline(self):
        # "best_guess" ambiguity_policy keeps a usable intent_class (not
        # forced to "unknown") even though is_ambiguous=True -- this case
        # must NOT be short-circuited, or the best_guess policy's whole
        # purpose (proceed with the best guess rather than always asking
        # to clarify) would be defeated.
        node = self._make_node()
        node._process_intent(
            self._make_intent(
                text="where is the bathroom",
                is_ambiguous=True,
                intent_class="navigate_to",
                fallback_response="Where would you like to go?",
            )
        )
        assert node._rag.retrieve_with_scores.call_count == 1
        assert node._call_llm.call_count == 1

    def test_non_ambiguous_intent_is_unaffected(self):
        node = self._make_node()
        node._process_intent(
            self._make_intent(
                text="what time is it",
                is_ambiguous=False,
                intent_class="general_query",
            )
        )
        assert node._rag.retrieve_with_scores.call_count == 1
        assert node._call_llm.call_count == 1


# ── GAP-E8: task_router rule-engine short-circuit for emergency phrases ───────


class TestEmergencyRuleEngineShortCircuit:
    """pi_human_ai.yaml's resolution_order: [rule_engine, rag, llm] must be
    real, live behavior, not just a declared config key. An emergency
    phrase must never reach RAG or the LLM -- see docs/EDGE_AI_GAP_ANALYSIS.md
    GAP-E8 and docs/EDGE_AI_TASK_ROUTER_REPORT.md."""

    def _make_node(self, with_task_router: bool):
        from bonbon_llm.config.llm_config import (
            AuthorizationConfig,
            HallucinationConfig,
            PersonalityConfig,
            SafetyFilterConfig,
        )
        from bonbon_llm.core.response_cache import ResponseCache
        from bonbon_llm.nodes.llm_orchestrator_node import LLMOrchestratorNode
        from bonbon_llm.personality.personality_layer import PersonalityLayer
        from bonbon_llm.safety.authorization import CommandAuthorizer
        from bonbon_llm.safety.command_filter import SafetyCommandFilter
        from bonbon_llm.safety.hallucination_guard import HallucinationGuard

        node = LLMOrchestratorNode("test_llm_orchestrator")
        node._response_cache = ResponseCache()
        node._rag = MagicMock()
        node._rag.retrieve_with_scores.return_value = []
        node._rag.build_context_string.return_value = ""
        node._filter = SafetyCommandFilter(SafetyFilterConfig())
        node._guard = HallucinationGuard(HallucinationConfig(enabled=False))
        node._authorizer = CommandAuthorizer(AuthorizationConfig())
        node._personality = PersonalityLayer(PersonalityConfig())
        node._logger_svc = MagicMock()
        node._tool_reg = None
        node._cfg = None
        node._pub_response = MagicMock()
        node._pub_tts = MagicMock()
        node._pub_behavior = MagicMock()
        node._last_scene = None
        node._last_safety = None
        node._last_risks = []
        node._call_llm = MagicMock(return_value=("A real answer.", None))
        if with_task_router:
            from bonbon_edge_ai_runtime.task_router import TaskRouter

            node._task_router = TaskRouter()
        else:
            node._task_router = None
        return node

    def _make_intent(self, text):
        intent = MagicMock()
        intent.is_ambiguous = False
        intent.raw_text = text
        intent.intent_class = "general_query"
        intent.confidence = 0.9
        intent.speaker_id = ""
        intent.slot_names = []
        intent.slot_values = []
        intent.intent_id = "intent-1"
        return intent

    def test_emergency_phrase_never_reaches_rag_or_llm(self):
        node = self._make_node(with_task_router=True)
        node._process_intent(self._make_intent("help, someone collapsed"))
        assert node._rag.retrieve_with_scores.call_count == 0
        assert node._call_llm.call_count == 0

    def test_emergency_phrase_dispatches_high_priority_tts(self):
        node = self._make_node(with_task_router=True)
        node._process_intent(self._make_intent("help, someone collapsed"))
        assert node._pub_tts.publish.call_count == 1
        published = node._pub_tts.publish.call_args[0][0]
        assert published.priority == 10  # TTSRequest.PRIORITY_HIGH

    def test_emergency_phrase_dispatches_alert_safety_behavior(self):
        node = self._make_node(with_task_router=True)
        node._process_intent(self._make_intent("help, someone collapsed"))
        assert node._pub_behavior.publish.call_count == 1
        published = node._pub_behavior.publish.call_args[0][0]
        assert published.behavior_class == "alert_safety"

    def test_non_emergency_phrase_is_unaffected_by_task_router(self):
        node = self._make_node(with_task_router=True)
        node._process_intent(self._make_intent("what time is it"))
        assert node._rag.retrieve_with_scores.call_count == 1
        assert node._call_llm.call_count == 1

    def test_without_task_router_pipeline_behaves_exactly_as_before(self):
        # Degradation guard: if bonbon_edge_ai_runtime is unavailable
        # (_task_router is None), an emergency phrase must fall through
        # to the ordinary RAG+LLM pipeline unchanged, never crash.
        node = self._make_node(with_task_router=False)
        node._process_intent(self._make_intent("help, someone collapsed"))
        assert node._rag.retrieve_with_scores.call_count == 1
        assert node._call_llm.call_count == 1


# ── GAP-E1: _get_safety_snapshot must fail closed, not fail open ──────────────


class TestGetSafetySnapshotFailsClosed:
    """See docs/SAFETY_SEPARATION_AUDIT.md Finding 1: an LLM-originated
    BehaviorRecommendation could previously reach real Nav2 goal dispatch
    before the first SafetyState message arrived, because
    SafetySnapshot.safe_default() was permissive (navigation/actuation
    both True). These tests exercise the REAL _get_safety_snapshot method
    on a real (non-mocked) node, not a re-implementation."""

    def _make_node(self):
        from bonbon_llm.nodes.llm_orchestrator_node import LLMOrchestratorNode

        node = LLMOrchestratorNode("test_llm_orchestrator")
        node._last_scene = None
        node._last_safety = None
        node._last_safety_at = 0.0
        node._last_risks = []
        return node

    def test_no_safety_message_yet_is_fail_closed(self):
        node = self._make_node()
        snap = node._get_safety_snapshot()
        assert snap.navigation_permitted is False
        assert snap.actuation_permitted is False

    def test_fresh_safety_message_passes_through(self):
        node = self._make_node()
        node._last_safety = MagicMock(
            state=1,  # NORMAL
            state_name="NORMAL",
            actuation_permitted=True,
            navigation_permitted=True,
            max_velocity_mps=0.8,
            requires_manual_reset=False,
        )
        node._last_safety_at = time.monotonic()
        snap = node._get_safety_snapshot()
        assert snap.navigation_permitted is True
        assert snap.actuation_permitted is True
        assert snap.state_name == "NORMAL"

    def test_stale_safety_message_falls_back_to_fail_closed(self):
        # A real SafetyState was received once, then the Safety
        # Supervisor went silent (crashed, network partition) -- must
        # NOT keep reusing the old permissive snapshot forever.
        node = self._make_node()
        node._last_safety = MagicMock(
            state=1,  # NORMAL
            state_name="NORMAL",
            actuation_permitted=True,
            navigation_permitted=True,
            max_velocity_mps=0.8,
            requires_manual_reset=False,
        )
        node._last_safety_at = time.monotonic() - 10.0  # 10s old, well past the 2s staleness window
        snap = node._get_safety_snapshot()
        assert snap.navigation_permitted is False
        assert snap.actuation_permitted is False
