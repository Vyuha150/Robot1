"""
bonbon_llm.core.langchain_bridge
=================================
LangChain chain builders for Ollama-backed LLM inference.

Lazy imports: if langchain or langchain_community are not installed
the module still loads; attempting to build a chain raises
``LangChainUnavailableError`` with an install hint.

Pipeline
--------
  system_prompt + rag_context + tool_schema
       ↓
  ChatOllama (ChatPromptTemplate)
       ↓
  StrOutputParser / structured tool output
"""

from __future__ import annotations

import logging
from typing import Any

from bonbon_llm.config.llm_config import LLMConfig

logger = logging.getLogger(__name__)


class LangChainUnavailableError(RuntimeError):
    pass


_INSTALL_HINT = "pip install langchain langchain-community langchain-ollama"


def _require_langchain():
    try:
        import langchain  # noqa: F401
    except ImportError as exc:
        raise LangChainUnavailableError(f"LangChain is not installed. {_INSTALL_HINT}") from exc


# ── Chain builders ────────────────────────────────────────────────────────────


def build_chat_chain(cfg: LLMConfig, system_prompt: str):
    """
    Build a simple ChatOllama | StrOutputParser chain.

    Returns a Runnable that accepts ``{"input": str, "context": str}``
    and yields a plain string.
    """
    _require_langchain()
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        from langchain_community.chat_models import ChatOllama  # type: ignore

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    llm = ChatOllama(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        temperature=cfg.ollama.temperature,
        num_predict=cfg.ollama.max_tokens,
        num_ctx=cfg.ollama.num_ctx,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("human", "{input}"),
        ]
    )

    chain = prompt | llm | StrOutputParser()
    return chain


def build_rag_chain(cfg: LLMConfig, system_prompt: str):
    """
    Build a ChatOllama chain that injects a ``{context}`` variable
    from RAG retrieval into the system message.

    Accepts ``{"input": str, "context": str}`` (context pre-formatted
    by RAGRetriever.build_context_string).
    """
    _require_langchain()
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        from langchain_community.chat_models import ChatOllama  # type: ignore

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    llm = ChatOllama(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        temperature=cfg.ollama.temperature,
        num_predict=cfg.ollama.max_tokens,
        num_ctx=cfg.ollama.num_ctx,
    )

    system_with_ctx = (
        system_prompt + "\n\n--- KNOWLEDGE BASE ---\n{context}\n--- END KNOWLEDGE BASE ---"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_with_ctx),
            ("human", "{input}"),
        ]
    )

    chain = prompt | llm | StrOutputParser()
    return chain


def build_tool_chain(cfg: LLMConfig, system_prompt: str, tools: list[dict[str, Any]]):
    """
    Build a chain with tool/function-calling bindings.

    ``tools`` is a list of OpenAI-compatible tool schemas:
    [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]

    Returns a Runnable that accepts ``{"input": str, "context": str}``
    and yields either a plain string or a tool-call dict.
    """
    _require_langchain()
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        from langchain_community.chat_models import ChatOllama  # type: ignore

    from langchain_core.prompts import ChatPromptTemplate

    llm = ChatOllama(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        temperature=cfg.ollama.temperature,
        num_predict=cfg.ollama.max_tokens,
        num_ctx=cfg.ollama.num_ctx,
    )

    # bind_tools is available in newer langchain-ollama builds
    try:
        llm_with_tools = llm.bind_tools(tools)
    except AttributeError:
        logger.warning("ChatOllama.bind_tools not available; tool calling disabled")
        llm_with_tools = llm

    system_with_ctx = (
        system_prompt + "\n\n--- KNOWLEDGE BASE ---\n{context}\n--- END KNOWLEDGE BASE ---"
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_with_ctx),
            ("human", "{input}"),
        ]
    )

    chain = prompt | llm_with_tools
    return chain


def invoke_chain(chain, input_text: str, context: str = "") -> str:
    """
    Safe chain invocation that always returns a plain string.

    Handles both StrOutputParser output (str) and AIMessage output (with
    tool_calls or .content), returning the text content in all cases.
    """
    result = chain.invoke({"input": input_text, "context": context})

    if isinstance(result, str):
        return result

    # AIMessage or similar
    if hasattr(result, "content"):
        return result.content or ""

    if isinstance(result, dict):
        return result.get("output", result.get("content", str(result)))

    return str(result)


def extract_tool_calls(chain_result: Any) -> list[dict[str, Any]]:
    """
    Extract tool call list from a chain result (AIMessage with tool_calls).
    Returns empty list if no tool calls or if result is plain text.
    """
    if hasattr(chain_result, "tool_calls"):
        return list(chain_result.tool_calls or [])
    if isinstance(chain_result, dict) and "tool_calls" in chain_result:
        return chain_result["tool_calls"] or []
    return []
