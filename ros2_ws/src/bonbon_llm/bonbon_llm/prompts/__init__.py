"""
bonbon_llm.prompts
==================
System prompts, context templates, and static fallback responses.
"""
from bonbon_llm.prompts.system_prompt import (
    SYSTEM_PROMPT,
    TOOL_INSTRUCTIONS,
    GROUNDING_FALLBACK_NOTE,
    build_context_string,
)
from bonbon_llm.prompts.response_templates import (
    FallbackTemplate,
    TEMPLATES,
    get_fallback,
    get_all_keys,
)

__all__ = [
    # System prompt
    "SYSTEM_PROMPT",
    "TOOL_INSTRUCTIONS",
    "GROUNDING_FALLBACK_NOTE",
    "build_context_string",
    # Fallback templates
    "FallbackTemplate",
    "TEMPLATES",
    "get_fallback",
    "get_all_keys",
]
