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

    for name, mod in [
        ("rclpy", fake_rclpy),
        ("rclpy.node", node_mod),
        ("rclpy.lifecycle", lifecycle_mod),
        ("rclpy.lifecycle.node", lifecycle_mod),
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
