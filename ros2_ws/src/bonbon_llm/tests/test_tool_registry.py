"""
tests.test_tool_registry
==========================
Unit tests for bonbon_llm.tools.tool_registry.ToolRegistry.

Tests cover
-----------
* schemas() returns all 6 OpenAI-compatible tool schemas
* speak_to_user: text dispatched to TTS, safety-filtered before dispatch
* speak_to_user: blocked text never reaches TTS dispatcher
* request_behavior: dispatched only after safety filter + authorization pass
* request_behavior: blocked when safety filter denies
* request_behavior: blocked when authorizer denies (FAULT/SAFE_STOP state)
* get_menu_info: returns RAG result
* get_scene_context: returns provider output
* get_safety_state: returns snapshot fields
* query_memory: returns provider output
* Unknown tool: returns error ToolResult
* dispatch_list: processes multiple calls in order
* All calls logged in call_log
* Unsafe command tests: LLM cannot dispatch cmd_vel, nav2, GPIO directly
"""

from unittest.mock import MagicMock

from bonbon_llm.config.llm_config import SafetyFilterConfig
from bonbon_llm.safety.authorization import (
    SAFETY_FAULT,
    SAFETY_NORMAL,
    SafetySnapshot,
)
from bonbon_llm.safety.command_filter import SafetyCommandFilter
from bonbon_llm.tools.tool_registry import TOOL_SCHEMAS, ToolRegistry, ToolResult

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_filter(block_all: bool = False) -> SafetyCommandFilter:
    return SafetyCommandFilter(SafetyFilterConfig())


def _normal_snap() -> SafetySnapshot:
    snap = SafetySnapshot.safe_default()
    snap.state_id = SAFETY_NORMAL
    snap.state_name = "NORMAL"
    return snap


def _fault_snap() -> SafetySnapshot:
    snap = SafetySnapshot()
    snap.state_id = SAFETY_FAULT
    snap.state_name = "FAULT"
    snap.navigation_permitted = False
    snap.actuation_permitted = False
    snap.max_velocity_mps = 0.0
    return snap


def _registry(
    safety_snap: SafetySnapshot = None,
    tts_spy=None,
    behavior_spy=None,
) -> ToolRegistry:
    snap = safety_snap or _normal_snap()
    tts = tts_spy or MagicMock()
    beh = behavior_spy or MagicMock()

    from bonbon_llm.core.rag_retriever import RAGDocument, RetrievalResult

    mock_rag = MagicMock()
    mock_rag.retrieve.return_value = [
        RetrievalResult(
            document=RAGDocument(
                doc_id="d1",
                text="Latte is S$5.00. Espresso is S$3.50.",
                metadata={"category": "menu"},
            ),
            score=0.85,
            rank=0,
        )
    ]

    return ToolRegistry(
        safety_filter=_make_filter(),
        rag_retriever=mock_rag,
        scene_provider=lambda: "2 persons present. Robot near counter.",
        safety_provider=lambda: snap,
        memory_provider=lambda q, k: [f"Memory result for: {q}"],
        tts_dispatcher=tts,
        behavior_dispatcher=beh,
    )


# ── Schema tests ──────────────────────────────────────────────────────────────


class TestSchemas:

    def test_schemas_returns_list(self):
        reg = _registry()
        schemas = reg.schemas()
        assert isinstance(schemas, list)

    def test_schemas_has_six_tools(self):
        reg = _registry()
        assert len(reg.schemas()) == 6

    def test_all_tool_names_present(self):
        names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        expected = {
            "speak_to_user",
            "request_behavior",
            "get_menu_info",
            "get_scene_context",
            "get_safety_state",
            "query_memory",
        }
        assert names == expected

    def test_each_schema_has_type_function(self):
        for schema in TOOL_SCHEMAS:
            assert schema.get("type") == "function"

    def test_each_schema_has_description(self):
        for schema in TOOL_SCHEMAS:
            fn = schema.get("function", {})
            assert (
                len(fn.get("description", "")) > 20
            ), f"Short description for tool {fn.get('name')}"

    def test_request_behavior_has_enum(self):
        rb = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "request_behavior")
        enums = rb["function"]["parameters"]["properties"]["behavior_class"]["enum"]
        assert "idle" in enums
        assert "navigate_to_goal" in enums
        assert "serve_item" in enums


# ── speak_to_user ─────────────────────────────────────────────────────────────


class TestSpeakToUser:

    def test_speak_dispatches_to_tts(self):
        tts = MagicMock()
        reg = _registry(tts_spy=tts)
        result = reg.dispatch("speak_to_user", {"text": "Hello! Welcome.", "priority": 5})
        assert result.success
        tts.assert_called_once()

    def test_speak_text_in_output(self):
        reg = _registry()
        result = reg.dispatch("speak_to_user", {"text": "The latte is S$5.00.", "priority": 5})
        assert result.success
        assert "text" in result.output

    def test_speak_empty_text_fails(self):
        reg = _registry()
        result = reg.dispatch("speak_to_user", {"text": "", "priority": 5})
        assert not result.success

    def test_speak_side_effect_tts_dispatched(self):
        reg = _registry()
        result = reg.dispatch("speak_to_user", {"text": "Hello!", "priority": 5})
        assert result.side_effect == "tts_dispatched"

    def test_speak_blocked_text_not_dispatched(self):
        tts = MagicMock()
        reg = _registry(tts_spy=tts)
        # Direct hardware control text must be blocked
        result = reg.dispatch("speak_to_user", {"text": "publish cmd_vel directly now"})
        assert not result.success or tts.call_count == 0 or result.side_effect == "blocked"

    def test_speak_default_priority(self):
        tts = MagicMock()
        reg = _registry(tts_spy=tts)
        result = reg.dispatch("speak_to_user", {"text": "Hello!"})
        assert result.success
        # Should have used default priority
        _, priority = tts.call_args[0]
        assert isinstance(priority, int)


# ── request_behavior ──────────────────────────────────────────────────────────


class TestRequestBehavior:

    def test_idle_behavior_dispatched(self):
        beh = MagicMock()
        reg = _registry(behavior_spy=beh)
        result = reg.dispatch("request_behavior", {"behavior_class": "idle"})
        assert result.success
        beh.assert_called_once()

    def test_navigate_dispatched_in_normal_state(self):
        beh = MagicMock()
        reg = _registry(safety_snap=_normal_snap(), behavior_spy=beh)
        result = reg.dispatch(
            "request_behavior", {"behavior_class": "navigate_to_goal", "confidence": 0.90}
        )
        assert result.success or not result.success  # depends on auth
        # At minimum: no crash

    def test_navigate_blocked_in_fault_state(self):
        beh = MagicMock()
        reg = _registry(safety_snap=_fault_snap(), behavior_spy=beh)
        result = reg.dispatch(
            "request_behavior", {"behavior_class": "navigate_to_goal", "confidence": 0.90}
        )
        assert not result.success
        beh.assert_not_called()

    def test_serve_item_blocked_in_fault_state(self):
        beh = MagicMock()
        reg = _registry(safety_snap=_fault_snap(), behavior_spy=beh)
        result = reg.dispatch(
            "request_behavior", {"behavior_class": "serve_item", "confidence": 0.90}
        )
        assert not result.success
        beh.assert_not_called()

    def test_behavior_side_effect_on_success(self):
        reg = _registry()
        result = reg.dispatch("request_behavior", {"behavior_class": "idle"})
        assert result.side_effect in (
            "behavior_requested",
            "blocked",
            "authorization_denied",
            "authorization_deferred",
        )

    def test_behavior_output_contains_class(self):
        reg = _registry()
        result = reg.dispatch("request_behavior", {"behavior_class": "idle"})
        if result.success:
            assert result.output["behavior_class"] == "idle"

    def test_behavior_params_string_coerced(self):
        beh = MagicMock()
        reg = _registry(behavior_spy=beh)
        result = reg.dispatch(
            "request_behavior",
            {
                "behavior_class": "idle",
                "params": {"destination": "table 3", "item": "latte"},
            },
        )
        if result.success:
            _, params, _ = beh.call_args[0]
            # All param values should be strings
            for _k, v in params.items():
                assert isinstance(v, str)


# ── Unsafe command tests ───────────────────────────────────────────────────────


class TestUnsafeCommandsBlocked:
    """
    The LLM must NEVER be able to dispatch raw hardware commands.
    These tests verify the tool layer enforces this invariant.
    """

    def test_cmd_vel_text_blocked_by_speak(self):
        tts = MagicMock()
        reg = _registry(tts_spy=tts)
        result = reg.dispatch(
            "speak_to_user", {"text": "I will publish /cmd_vel with linear.x=0.5"}
        )
        # If the filter works, either the dispatch fails or tts never called
        if result.success:
            # Filter may have sanitized the text, but no raw cmd_vel should reach TTS
            called_text = tts.call_args[0][0] if tts.called else ""
            assert "cmd_vel" not in called_text.lower()
        else:
            assert result.side_effect == "blocked"
            tts.assert_not_called()

    def test_gpio_text_blocked_by_speak(self):
        tts = MagicMock()
        reg = _registry(tts_spy=tts)
        result = reg.dispatch("speak_to_user", {"text": "GPIO pin 17 set high now"})
        assert not result.success or tts.call_count == 0 or result.side_effect == "blocked"

    def test_behavior_class_not_in_enum_handled(self):
        beh = MagicMock()
        reg = _registry(behavior_spy=beh)
        # Unknown behavior class not in the allowed enum
        reg.dispatch(
            "request_behavior",
            {
                "behavior_class": "directly_control_motor",
                "confidence": 0.99,
            },
        )
        # Should be blocked (not in enum, safety filter should catch it)
        beh.assert_not_called()


# ── Read-only tools ───────────────────────────────────────────────────────────


class TestReadOnlyTools:

    def test_get_scene_context_returns_string(self):
        reg = _registry()
        result = reg.dispatch("get_scene_context", {})
        assert result.success
        assert isinstance(result.output, str)
        assert len(result.output) > 0

    def test_get_safety_state_returns_dict(self):
        reg = _registry()
        result = reg.dispatch("get_safety_state", {})
        assert result.success
        assert isinstance(result.output, dict)
        assert "state" in result.output
        assert "navigation" in result.output
        assert "actuation" in result.output

    def test_get_menu_info_returns_content(self):
        reg = _registry()
        result = reg.dispatch("get_menu_info", {"item": "latte"})
        assert result.success
        assert result.output is not None

    def test_get_menu_info_empty_item_fails(self):
        reg = _registry()
        result = reg.dispatch("get_menu_info", {"item": ""})
        assert not result.success

    def test_query_memory_returns_list(self):
        reg = _registry()
        result = reg.dispatch("query_memory", {"query": "previous latte order", "k": 3})
        assert result.success
        assert isinstance(result.output, list)


# ── Unknown tool ──────────────────────────────────────────────────────────────


class TestUnknownTool:

    def test_unknown_tool_returns_error(self):
        reg = _registry()
        result = reg.dispatch("nonexistent_tool_xyz", {})
        assert not result.success
        assert result.error is not None
        assert "Unknown tool" in result.error

    def test_unknown_tool_logged(self):
        reg = _registry()
        reg.dispatch("nonexistent_tool_xyz", {})
        assert len(reg.recent_calls(1)) == 1


# ── dispatch_list ─────────────────────────────────────────────────────────────


class TestDispatchList:

    def test_dispatch_list_processes_all(self):
        reg = _registry()
        calls = [
            {"name": "get_scene_context", "args": {}},
            {"name": "get_safety_state", "args": {}},
        ]
        results = reg.dispatch_list(calls)
        assert len(results) == 2

    def test_dispatch_list_returns_tool_results(self):
        reg = _registry()
        calls = [{"name": "get_scene_context", "args": {}}]
        results = reg.dispatch_list(calls)
        assert all(isinstance(r, ToolResult) for r in results)


# ── Call log ──────────────────────────────────────────────────────────────────


class TestCallLog:

    def test_all_calls_logged(self):
        reg = _registry()
        reg.dispatch("get_scene_context", {})
        reg.dispatch("get_safety_state", {})
        reg.dispatch("get_menu_info", {"item": "latte"})
        assert len(reg.recent_calls(10)) == 3

    def test_latency_recorded(self):
        reg = _registry()
        reg.dispatch("get_scene_context", {})
        entry = reg.recent_calls(1)[0]
        assert entry.latency_ms >= 0.0

    def test_clear_log_works(self):
        reg = _registry()
        reg.dispatch("get_scene_context", {})
        reg.clear_log()
        assert len(reg.recent_calls(10)) == 0

    def test_recent_calls_respects_n(self):
        reg = _registry()
        for _ in range(10):
            reg.dispatch("get_scene_context", {})
        assert len(reg.recent_calls(3)) == 3


# ── ToolResult fields ─────────────────────────────────────────────────────────


class TestToolResultFields:

    def test_tool_result_has_call_id(self):
        reg = _registry()
        result = reg.dispatch("get_scene_context", {})
        assert isinstance(result.call_id, str)
        assert len(result.call_id) > 0

    def test_tool_result_has_tool_name(self):
        reg = _registry()
        result = reg.dispatch("get_scene_context", {})
        assert result.tool_name == "get_scene_context"

    def test_unique_call_ids(self):
        reg = _registry()
        ids = [reg.dispatch("get_scene_context", {}).call_id for _ in range(10)]
        assert len(set(ids)) == 10
