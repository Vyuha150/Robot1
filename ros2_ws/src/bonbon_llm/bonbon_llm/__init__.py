"""
bonbon_llm
==========
LLM + Response Generation Module for the BonBon service robot.

Architecture summary
--------------------
                    ┌──────────────────────────────────────────┐
  /perception/      │          LLMOrchestratorNode             │
  intent ──────────►│                                          │
  /perception/      │  RAGRetriever ──► OllamaClient           │
  scene  ──────────►│       │               │                  │
  /bonbon/safety/   │       ▼               ▼                  │
  state  ──────────►│  HallucinationGuard  LangChainBridge     │
                    │       │                                  │
                    │  SafetyCommandFilter                     │
                    │       │                                  │
                    │  CommandAuthorizer                       │
                    │       │                                  │
                    │  PersonalityLayer                        │
                    │       │                                  │
  /llm/response ◄──│  ResponseLogger                          │
  /bonbon/tts  ◄──│                                           │
  /perception/ ◄──│                                           │
  behavior         └──────────────────────────────────────────┘

Key constraints
---------------
* The LLM NEVER directly controls actuators or navigation.
* All motion requests pass through Safety Supervisor + Behavior Engine.
* All responses are logged for audit.
* Optional dependencies (langchain, chromadb, faiss, ollama,
  sentence-transformers) degrade gracefully — the node always starts.
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "BonBon Robot AI Team"

# ── Config ────────────────────────────────────────────────────────────────────
from bonbon_llm.config.llm_config import (
    AuthorizationConfig,
    HallucinationConfig,
    LLMConfig,
    OllamaConfig,
    PersonalityConfig,
    RAGConfig,
    SafetyFilterConfig,
)
from bonbon_llm.core.langchain_bridge import LangChainUnavailableError

# ── Core ──────────────────────────────────────────────────────────────────────
from bonbon_llm.core.ollama_client import OllamaClient, OllamaResponse
from bonbon_llm.core.rag_retriever import RAGDocument, RAGRetriever, RetrievalResult
from bonbon_llm.core.response_logger import LogEntry, ResponseLogger

# ── Personality ───────────────────────────────────────────────────────────────
from bonbon_llm.personality.personality_layer import PersonalityLayer
from bonbon_llm.prompts.response_templates import TEMPLATES, get_all_keys, get_fallback

# ── Prompts ───────────────────────────────────────────────────────────────────
from bonbon_llm.prompts.system_prompt import (
    GROUNDING_FALLBACK_NOTE,
    SYSTEM_PROMPT,
    TOOL_INSTRUCTIONS,
    build_context_string,
)
from bonbon_llm.safety.authorization import (
    AuthorizationResult,
    AuthStatus,
    CommandAuthorizer,
    SafetySnapshot,
)

# ── Safety ────────────────────────────────────────────────────────────────────
from bonbon_llm.safety.command_filter import FilterResult, FilterStatus, SafetyCommandFilter
from bonbon_llm.safety.hallucination_guard import GuardResult, HallucinationGuard

# ── Tools ─────────────────────────────────────────────────────────────────────
from bonbon_llm.tools.tool_registry import TOOL_SCHEMAS, ToolRegistry, ToolResult

__all__ = [
    # Meta
    "__version__",
    # Config
    "OllamaConfig",
    "RAGConfig",
    "SafetyFilterConfig",
    "HallucinationConfig",
    "PersonalityConfig",
    "AuthorizationConfig",
    "LLMConfig",
    # Core
    "OllamaClient",
    "OllamaResponse",
    "RAGRetriever",
    "RAGDocument",
    "RetrievalResult",
    "ResponseLogger",
    "LogEntry",
    "LangChainUnavailableError",
    # Safety
    "FilterStatus",
    "FilterResult",
    "SafetyCommandFilter",
    "AuthStatus",
    "AuthorizationResult",
    "SafetySnapshot",
    "CommandAuthorizer",
    "GuardResult",
    "HallucinationGuard",
    # Personality
    "PersonalityLayer",
    # Prompts
    "SYSTEM_PROMPT",
    "TOOL_INSTRUCTIONS",
    "GROUNDING_FALLBACK_NOTE",
    "build_context_string",
    "get_fallback",
    "get_all_keys",
    "TEMPLATES",
    # Tools
    "TOOL_SCHEMAS",
    "ToolResult",
    "ToolRegistry",
]
