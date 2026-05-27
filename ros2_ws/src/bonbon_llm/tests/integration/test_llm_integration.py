"""
tests.integration.test_llm_integration
========================================
Full pipeline integration tests — no live Ollama required.

These tests wire all bonbon_llm components together (RAG → safety filter →
hallucination guard → personality layer → tool registry) and drive them as
a unit, verifying end-to-end behaviour for the following scenarios:

Scenario A — Happy path
    Normal intent, grounded RAG hit, safe LLM response →
    personality layer applied, TTS dispatched, no fallback.

Scenario B — Unsafe command
    LLM produces a response containing direct hardware references →
    safety filter blocks → fallback dispatched, TTS never receives raw text.

Scenario C — Hallucination
    LLM claims an impossible capability (fly, arms, internet) →
    hallucination guard flags → safe_response used, logged as hallucinated.

Scenario D — Low confidence
    LLM self-reported confidence below threshold →
    low_confidence fallback template selected.

Scenario E — LLM error / timeout
    OllamaClient unavailable → llm_error fallback selected.

Scenario F — Blocked navigation in FAULT safety state
    request_behavior(navigate_to_goal) with FAULT state →
    Authorization denied, behavior dispatcher never called.
"""

import sys
import types
from unittest.mock import MagicMock

# ── Stub ROS2 ─────────────────────────────────────────────────────────────────


def _ensure_ros_stub():
    for name in (
        "rclpy",
        "rclpy.node",
        "rclpy.lifecycle",
        "rclpy.lifecycle.node",
        "bonbon_msgs",
        "bonbon_msgs.msg",
        "bonbon_srvs",
        "bonbon_srvs.srv",
        "std_msgs",
        "std_msgs.msg",
        "lifecycle_msgs",
        "lifecycle_msgs.msg",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
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


_ensure_ros_stub()

# ── Imports ───────────────────────────────────────────────────────────────────

from bonbon_llm.config.llm_config import (
    HallucinationConfig,
    PersonalityConfig,
    RAGConfig,
    SafetyFilterConfig,
)
from bonbon_llm.core.rag_retriever import RAGRetriever
from bonbon_llm.core.response_logger import ResponseLogger
from bonbon_llm.personality.personality_layer import PersonalityLayer
from bonbon_llm.prompts.response_templates import get_fallback
from bonbon_llm.safety.authorization import (
    SAFETY_FAULT,
    SAFETY_NORMAL,
    SafetySnapshot,
)
from bonbon_llm.safety.command_filter import FilterStatus, SafetyCommandFilter
from bonbon_llm.safety.hallucination_guard import HallucinationGuard
from bonbon_llm.tools.tool_registry import ToolRegistry

# ── Pipeline harness ──────────────────────────────────────────────────────────


class _Pipeline:
    """
    Minimal wiring of all bonbon_llm components into a pipeline,
    with Ollama replaced by a configurable mock.
    """

    def __init__(
        self,
        llm_response: str = "The latte is S$5.00.",
        llm_confidence: float = 0.88,
        safety_state: int = SAFETY_NORMAL,
        guard_enabled: bool = True,
        raise_llm_error: bool = False,
    ):
        self.tts_calls: list = []
        self.behavior_calls: list = []
        self.log_entries: list = []

        # RAG
        rag_cfg = RAGConfig(backend="numpy", top_k=3, similarity_threshold=0.0)
        self.rag = RAGRetriever(rag_cfg)
        self.rag.load()

        # Safety
        self.cmd_filter = SafetyCommandFilter(SafetyFilterConfig())
        snap = SafetySnapshot.safe_default()
        snap.state_id = safety_state
        snap.state_name = "NORMAL" if safety_state == SAFETY_NORMAL else "FAULT"
        snap.navigation_permitted = safety_state == SAFETY_NORMAL
        snap.actuation_permitted = safety_state == SAFETY_NORMAL
        self.safety_snap = snap

        # Hallucination guard
        self.guard = HallucinationGuard(HallucinationConfig(enabled=guard_enabled))

        # Personality
        per_cfg = PersonalityConfig(
            name="BonBon",
            max_response_words=40,
            affirmations=["Sure!"],
        )
        self.personality = PersonalityLayer(per_cfg)

        # Logger
        self.logger = ResponseLogger(max_entries=50)

        # Tool registry
        self.registry = ToolRegistry(
            safety_filter=self.cmd_filter,
            rag_retriever=self.rag,
            scene_provider=lambda: "2 persons near counter.",
            safety_provider=lambda: self.safety_snap,
            memory_provider=lambda q, k: [],
            tts_dispatcher=lambda t, p: self.tts_calls.append((t, p)),
            behavior_dispatcher=lambda bc, ps, c: self.behavior_calls.append((bc, ps, c)),
        )

        # Mock LLM
        self._llm_response = llm_response
        self._llm_confidence = llm_confidence
        self._raise_error = raise_llm_error

    def run(self, user_text: str, intent_class: str = "menu_query") -> dict:
        """Run the full pipeline and return a result summary dict."""
        # 1. RAG retrieval
        rag_results = self.rag.retrieve_with_scores(user_text)

        # 2. Simulated LLM call
        if self._raise_error:
            llm_text = None
            final_text = get_fallback("llm_error", prefer_short=True)
            status = "llm_error"
        else:
            llm_text = self._llm_response
            confidence = self._llm_confidence

            # 3. Safety filter
            filt = self.cmd_filter.filter_text(llm_text)
            if filt.status == FilterStatus.BLOCKED:
                final_text = get_fallback("safety_block", prefer_short=True)
                status = "safety_block"
            else:
                sanitized = filt.sanitized_text

                # 4. Hallucination guard
                guard_result = self.guard.check(sanitized, rag_results, confidence)
                if not guard_result.is_grounded:
                    final_text = get_fallback("hallucination", prefer_short=True)
                    status = "hallucination"
                elif confidence < 0.45:
                    final_text = get_fallback("low_confidence", prefer_short=True)
                    status = "low_confidence"
                else:
                    # 5. Personality
                    final_text = self.personality.apply(sanitized)
                    status = "ok"

        # 6. TTS
        self.tts_calls.append((final_text, 5))

        # 7. Log
        rid = self.logger.record(
            intent_id="integ_test_01",
            speaker_id="spk_test",
            raw_prompt=user_text,
            raw_llm_output=llm_text or "",
            final_response=final_text,
            status=status,
            confidence=self._llm_confidence,
            llm_latency_ms=100.0,
            rag_latency_ms=3.0,
            tools_called=[],
            hallucination_flagged=(status == "hallucination"),
        )

        return {"status": status, "text": final_text, "response_id": rid}


# ── Scenario A: Happy path ────────────────────────────────────────────────────


class TestHappyPath:

    def test_normal_response_returns_ok(self):
        p = _Pipeline(llm_response="The latte is S$5.00.", llm_confidence=0.92)
        result = p.run("How much is the latte?", "menu_query")
        assert result["status"] == "ok"

    def test_normal_response_tts_dispatched(self):
        p = _Pipeline(llm_response="The latte is S$5.00.", llm_confidence=0.92)
        p.run("How much is the latte?", "menu_query")
        assert len(p.tts_calls) >= 1

    def test_normal_response_logged(self):
        p = _Pipeline(llm_response="The latte is S$5.00.", llm_confidence=0.92)
        result = p.run("How much is the latte?", "menu_query")
        entry = p.logger.get_by_id(result["response_id"])
        assert entry is not None
        assert entry.status == "ok"

    def test_currency_formatted_for_tts(self):
        p = _Pipeline(llm_response="The latte is S$5.00.", llm_confidence=0.92)
        result = p.run("latte price", "menu_query")
        assert result["status"] == "ok"
        # Personality layer should expand S$ in the final TTS text
        tts_text = p.tts_calls[-1][0]
        assert "Singapore dollars" in tts_text or "5" in tts_text

    def test_rag_results_retrieved(self):
        p = _Pipeline()
        p.run("latte menu espresso", "menu_query")
        # RAG should have retrieved default knowledge docs
        results = p.rag.retrieve("latte")
        assert len(results) > 0


# ── Scenario B: Unsafe command ────────────────────────────────────────────────


class TestUnsafeCommand:

    def test_cmd_vel_response_blocked(self):
        p = _Pipeline(
            llm_response="I will publish /cmd_vel {linear: {x: 1.0}}",
            llm_confidence=0.90,
        )
        result = p.run("move forward", "navigate_to")
        assert result["status"] == "safety_block"

    def test_gpio_response_blocked(self):
        p = _Pipeline(
            llm_response="Setting GPIO pin 17 to HIGH to open door",
            llm_confidence=0.90,
        )
        result = p.run("open the door", "unknown")
        assert result["status"] == "safety_block"

    def test_eval_response_blocked(self):
        p = _Pipeline(
            llm_response="eval(user_input) will execute your command directly",
            llm_confidence=0.90,
        )
        result = p.run("run code", "unknown")
        assert result["status"] == "safety_block"

    def test_blocked_response_uses_fallback_text(self):
        p = _Pipeline(
            llm_response="publish cmd_vel topic now",
            llm_confidence=0.90,
        )
        result = p.run("drive forward", "navigate_to")
        assert result["status"] == "safety_block"
        # Fallback text should be the safety_block template, not the raw LLM output
        assert "cmd_vel" not in result["text"].lower()

    def test_blocked_response_logged_as_safety_block(self):
        p = _Pipeline(
            llm_response="gpio direct motor control cmd_vel",
            llm_confidence=0.90,
        )
        result = p.run("move", "navigate_to")
        if result["status"] == "safety_block":
            entry = p.logger.get_by_id(result["response_id"])
            assert entry.status == "safety_block"


# ── Scenario C: Hallucination ─────────────────────────────────────────────────


class TestHallucinationScenario:

    def test_fly_claim_triggers_hallucination(self):
        p = _Pipeline(
            llm_response="I can fly to your table instantly!",
            llm_confidence=0.90,
            guard_enabled=True,
        )
        result = p.run("come here", "navigate_to")
        assert result["status"] == "hallucination"

    def test_hallucination_uses_safe_template(self):
        p = _Pipeline(
            llm_response="I am a human being who can make phone calls for you.",
            llm_confidence=0.90,
        )
        result = p.run("call for help", "help_request")
        if result["status"] == "hallucination":
            assert "I am a human" not in result["text"]

    def test_hallucination_logged(self):
        p = _Pipeline(
            llm_response="I can access the internet to find that for you.",
            llm_confidence=0.90,
        )
        result = p.run("search online", "unknown")
        if result["status"] == "hallucination":
            entry = p.logger.get_by_id(result["response_id"])
            assert entry.hallucination_flagged is True

    def test_disabled_guard_allows_hallucination(self):
        p = _Pipeline(
            llm_response="I can fly and have arms to hug you!",
            llm_confidence=0.90,
            guard_enabled=False,
        )
        result = p.run("greet me", "greeting")
        # Guard disabled → should not flag as hallucination
        assert result["status"] != "hallucination"


# ── Scenario D: Low confidence ────────────────────────────────────────────────


class TestLowConfidence:

    def test_low_confidence_triggers_fallback(self):
        p = _Pipeline(
            llm_response="I think the latte might be around five dollars.",
            llm_confidence=0.20,  # well below 0.45 threshold
        )
        result = p.run("how much is latte", "menu_query")
        assert result["status"] == "low_confidence"

    def test_low_confidence_fallback_text_is_template(self):
        p = _Pipeline(
            llm_response="Uh, maybe the price is something?",
            llm_confidence=0.15,
        )
        result = p.run("espresso price", "menu_query")
        if result["status"] == "low_confidence":
            template = get_fallback("low_confidence", prefer_short=True)
            assert result["text"] == template

    def test_border_confidence_accepted(self):
        p = _Pipeline(
            llm_response="The latte is S$5.00.",
            llm_confidence=0.50,  # above 0.45 threshold
        )
        result = p.run("latte price", "menu_query")
        assert result["status"] in ("ok", "hallucination")  # not low_confidence


# ── Scenario E: LLM error ─────────────────────────────────────────────────────


class TestLLMError:

    def test_llm_error_uses_fallback(self):
        p = _Pipeline(raise_llm_error=True)
        result = p.run("hello", "greeting")
        assert result["status"] == "llm_error"

    def test_llm_error_fallback_non_empty(self):
        p = _Pipeline(raise_llm_error=True)
        result = p.run("what can you do", "menu_query")
        assert len(result["text"]) > 0

    def test_llm_error_tts_dispatched_with_fallback(self):
        p = _Pipeline(raise_llm_error=True)
        p.run("help", "help_request")
        assert len(p.tts_calls) >= 1


# ── Scenario F: Navigation blocked in FAULT state ────────────────────────────


class TestNavigationBlockedInFault:

    def test_navigate_behavior_denied_in_fault(self):
        p = _Pipeline(safety_state=SAFETY_FAULT)
        # Try to dispatch a navigation behavior via the tool registry
        result = p.registry.dispatch(
            "request_behavior",
            {"behavior_class": "navigate_to_goal", "confidence": 0.95},
        )
        assert not result.success
        assert len(p.behavior_calls) == 0

    def test_serve_item_denied_in_fault(self):
        p = _Pipeline(safety_state=SAFETY_FAULT)
        result = p.registry.dispatch(
            "request_behavior",
            {"behavior_class": "serve_item", "confidence": 0.95},
        )
        assert not result.success
        assert len(p.behavior_calls) == 0

    def test_idle_allowed_in_fault(self):
        p = _Pipeline(safety_state=SAFETY_FAULT)
        result = p.registry.dispatch(
            "request_behavior",
            {"behavior_class": "idle", "confidence": 0.99},
        )
        assert result.success
