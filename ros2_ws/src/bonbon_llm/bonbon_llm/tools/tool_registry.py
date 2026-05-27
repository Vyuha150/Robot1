"""
bonbon_llm.tools.tool_registry
================================
Tool/function-calling architecture for the LLM orchestrator.

Each tool has three parts:
  1. JSON schema  — injected into the LLM prompt / bind_tools call
  2. Handler fn   — called when the LLM invokes the tool
  3. Guard        — safety check before handler executes

Architecture constraints
------------------------
* ``request_behavior`` is the ONLY tool that produces robot motion.
  It emits a BehaviorRecommendation that still passes through the
  Safety Supervisor and Behavior Engine — the LLM never directly
  controls hardware.
* All tool calls are logged via the ResponseLogger.
* Tools that read state (get_scene_context, get_safety_state) are
  always permitted regardless of safety state.
* Tools that produce side effects (speak_to_user, request_behavior)
  require SAFE filter status before execution.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from bonbon_llm.safety.command_filter import FilterStatus, SafetyCommandFilter
from bonbon_llm.safety.authorization import AuthorizationResult, AuthStatus, SafetySnapshot

logger = logging.getLogger(__name__)


# ── Tool schema (OpenAI-compatible) ──────────────────────────────────────────

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "speak_to_user",
            "description": (
                "Generate spoken text to be delivered to the customer via TTS. "
                "Use this to greet, respond to questions, confirm orders, or clarify intent. "
                "Text must be under 40 words and suitable for spoken delivery."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak aloud. Max 40 words.",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "1=low, 5=normal, 10=safety/urgent",
                        "default": 5,
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_behavior",
            "description": (
                "Request a robot behavior. This is the ONLY way to request robot movement "
                "or physical actions. The request passes through the Safety Supervisor "
                "and Behavior Engine before execution — you are NOT directly controlling hardware. "
                "Valid behavior_class values: idle, approach_person, serve_item, "
                "navigate_to_goal, stop_navigation, wait_for_input."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "behavior_class": {
                        "type": "string",
                        "enum": [
                            "idle", "approach_person", "serve_item",
                            "navigate_to_goal", "stop_navigation",
                            "wait_for_input",
                        ],
                    },
                    "params": {
                        "type": "object",
                        "description": "Behavior parameters, e.g. {\"destination\": \"table 3\", \"item\": \"latte\"}",
                        "additionalProperties": {"type": "string"},
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Your confidence this is the correct action (0.0–1.0).",
                    },
                },
                "required": ["behavior_class"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_menu_info",
            "description": (
                "Retrieve price, description, or availability of a menu item "
                "from the knowledge base. Always use this before quoting a price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "Menu item name, e.g. 'latte', 'espresso'.",
                    },
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_context",
            "description": (
                "Retrieve the current sensor scene summary: who is present, "
                "what objects are visible, and the robot's spatial context."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_safety_state",
            "description": (
                "Retrieve the current safety state. Check this before recommending "
                "any navigation or physical action."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_memory",
            "description": (
                "Search episodic memory for events relevant to the current query. "
                "Use to recall previous interactions with the same customer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query for memory search.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Max results to return (default 3).",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ── Tool result ───────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool_name:   str
    success:     bool
    output:      Any
    error:       Optional[str]      = None
    side_effect: Optional[str]      = None   # e.g. "tts_dispatched", "behavior_requested"
    call_id:     str                = field(default_factory=lambda: str(uuid.uuid4()))
    latency_ms:  float              = 0.0


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Manages tool schemas, handlers, and safe dispatch.

    Context providers are injected post-construction so the registry
    works in unit tests without live ROS2 data.
    """

    def __init__(
        self,
        safety_filter: SafetyCommandFilter,
        rag_retriever=None,      # RAGRetriever | None
        scene_provider=None,     # callable → scene description str
        safety_provider=None,    # callable → SafetySnapshot
        memory_provider=None,    # callable(query, k) → List[str]
        tts_dispatcher=None,     # callable(text, priority) → None
        behavior_dispatcher=None,# callable(behavior_class, params, confidence) → None
    ) -> None:
        self._filter       = safety_filter
        self._rag          = rag_retriever
        self._scene_fn     = scene_provider     or (lambda: "Scene data unavailable")
        self._safety_fn    = safety_provider    or (lambda: SafetySnapshot())
        self._memory_fn    = memory_provider    or (lambda q, k: [])
        self._tts_fn       = tts_dispatcher     or (lambda t, p: None)
        self._behavior_fn  = behavior_dispatcher or (lambda bc, ps, c: None)
        self._call_log:    List[ToolResult] = []

    def schemas(self) -> List[Dict[str, Any]]:
        """Return OpenAI-compatible tool schema list for LLM injection."""
        return TOOL_SCHEMAS

    def dispatch(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name with given arguments.

        Safety-checked before execution.  All calls appended to call_log.
        """
        t0 = time.perf_counter()
        handler = self._get_handler(tool_name)
        if handler is None:
            result = ToolResult(
                tool_name=tool_name, success=False, output=None,
                error=f"Unknown tool: {tool_name!r}",
            )
        else:
            try:
                result = handler(args)
            except Exception as exc:
                result = ToolResult(
                    tool_name=tool_name, success=False, output=None,
                    error=str(exc),
                )
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
        self._call_log.append(result)
        logger.debug("Tool %s → success=%s latency=%.1fms",
                     tool_name, result.success, result.latency_ms)
        return result

    def dispatch_list(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[ToolResult]:
        """Dispatch a list of tool calls from an AIMessage.tool_calls."""
        results = []
        for call in tool_calls:
            name = call.get("name", call.get("function", {}).get("name", ""))
            args_raw = call.get("args", call.get("function", {}).get("arguments", {}))
            args = args_raw if isinstance(args_raw, dict) else {}
            results.append(self.dispatch(name, args))
        return results

    def recent_calls(self, n: int = 10) -> List[ToolResult]:
        return self._call_log[-n:]

    def clear_log(self) -> None:
        self._call_log.clear()

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _get_handler(self, name: str) -> Optional[Callable]:
        return {
            "speak_to_user":    self._handle_speak,
            "request_behavior": self._handle_behavior,
            "get_menu_info":    self._handle_menu_info,
            "get_scene_context":self._handle_scene,
            "get_safety_state": self._handle_safety,
            "query_memory":     self._handle_memory,
        }.get(name)

    def _handle_speak(self, args: Dict[str, Any]) -> ToolResult:
        text     = str(args.get("text", "")).strip()
        priority = int(args.get("priority", 5))

        if not text:
            return ToolResult("speak_to_user", False, None, "Empty text")

        # Safety filter on speech output
        filt = self._filter.filter_text(text)
        if filt.status == FilterStatus.BLOCKED:
            return ToolResult(
                "speak_to_user", False, None,
                error=f"Speech blocked: {filt.reason}",
                side_effect="blocked",
            )

        self._tts_fn(filt.sanitized_text, priority)
        return ToolResult(
            "speak_to_user", True,
            {"text": filt.sanitized_text, "priority": priority},
            side_effect="tts_dispatched",
        )

    def _handle_behavior(self, args: Dict[str, Any]) -> ToolResult:
        bc         = str(args.get("behavior_class", "idle"))
        params     = {str(k): str(v) for k, v in args.get("params", {}).items()}
        confidence = float(args.get("confidence", 0.8))

        # Safety filter on behavior class
        filt = self._filter.filter_behavior(bc, confidence)
        if filt.status == FilterStatus.BLOCKED:
            return ToolResult(
                "request_behavior", False, None,
                error=f"Behavior blocked: {filt.reason}",
                side_effect="blocked",
            )

        # Authorization against live safety state
        safety = self._safety_fn()
        from bonbon_llm.safety.authorization import CommandAuthorizer, AuthorizationConfig
        auth = CommandAuthorizer(AuthorizationConfig()).authorize(bc, safety, confidence)
        if not auth.granted:
            return ToolResult(
                "request_behavior", False, None,
                error=f"Authorization {auth.status.value}: {auth.reason}",
                side_effect=f"authorization_{auth.status.value.lower()}",
            )

        self._behavior_fn(bc, params, confidence)
        return ToolResult(
            "request_behavior", True,
            {"behavior_class": bc, "params": params, "confidence": confidence},
            side_effect="behavior_requested",
        )

    def _handle_menu_info(self, args: Dict[str, Any]) -> ToolResult:
        item = str(args.get("item", "")).lower().strip()
        if not item:
            return ToolResult("get_menu_info", False, None, "No item specified")

        if self._rag is None:
            return ToolResult("get_menu_info", True, f"Menu data unavailable for {item!r}")

        results = self._rag.retrieve(item, k=2)
        if not results:
            return ToolResult("get_menu_info", True, f"No information found for {item!r}")

        snippets = "\n".join(r.document.text for r in results[:2])
        return ToolResult("get_menu_info", True, snippets)

    def _handle_scene(self, _: Dict[str, Any]) -> ToolResult:
        return ToolResult("get_scene_context", True, self._scene_fn())

    def _handle_safety(self, _: Dict[str, Any]) -> ToolResult:
        snap = self._safety_fn()
        return ToolResult("get_safety_state", True, {
            "state":       snap.state_name,
            "navigation":  snap.navigation_permitted,
            "actuation":   snap.actuation_permitted,
            "max_vel_mps": snap.max_velocity_mps,
        })

    def _handle_memory(self, args: Dict[str, Any]) -> ToolResult:
        query = str(args.get("query", ""))
        k     = int(args.get("k", 3))
        results = self._memory_fn(query, k)
        return ToolResult("query_memory", True, results)
