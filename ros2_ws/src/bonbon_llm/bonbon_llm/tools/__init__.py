"""
bonbon_llm.tools
================
Tool / function-calling architecture for the LLM orchestrator.

``request_behavior`` is the ONLY tool that produces robot motion; it
emits a BehaviorRecommendation that still passes through the Safety
Supervisor and Behavior Engine — the LLM never directly controls hardware.
"""

from bonbon_llm.tools.tool_registry import (
    TOOL_SCHEMAS,
    ToolRegistry,
    ToolResult,
)

__all__ = [
    "TOOL_SCHEMAS",
    "ToolResult",
    "ToolRegistry",
]
