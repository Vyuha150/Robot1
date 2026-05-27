"""
bonbon_perception_ai.langchain_tools.intent_chain
==================================================
LangChain chain for intent classification.

This module is imported lazily (only when backend = "langchain") so that
the absence of the langchain package does not break the default rule-based
pipeline.

API key contract
----------------
The key is NEVER hardcoded.  Sources checked in order:
  1. cfg.langchain_api_key (ROS2 param injection)
  2. OPENAI_API_KEY environment variable
  3. Raise RuntimeError with clear message

Fallback contract
-----------------
If the LLM call fails (network, timeout, invalid response), the caller in
IntentEngine catches the exception and falls back to the rule-based result.
"""

from __future__ import annotations

import os
import re

# ── Prompt template ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an intent classifier for a service robot called Bonbon.\n"
    "Given a user utterance and optional scene context, classify the intent "
    "into exactly one of the provided classes and give a confidence score.\n"
    "Respond with ONLY the format:  intent_class|confidence\n"
    "Example:  order_item|0.93\n"
    "Do not add any other text."
)

_HUMAN_TEMPLATE = (
    "Scene context: {context}\n"
    "Valid intent classes: {valid_classes}\n"
    'User said: "{text}"\n'
    "Classify:"
)

# ── Response parser ───────────────────────────────────────────────────────────

_RESPONSE_RE = re.compile(r"^\s*([a-z_]+)\s*\|\s*([01](?:\.\d+)?)\s*$", re.IGNORECASE)


def _parse_response(raw: str, valid_classes: set) -> tuple[str, float]:
    m = _RESPONSE_RE.match(raw.strip())
    if m:
        cls = m.group(1).lower()
        conf = float(m.group(2))
        if cls in valid_classes:
            return cls, min(1.0, max(0.0, conf))
    raise ValueError(f"Cannot parse LangChain response: {raw!r}")


# ── Chain builder ─────────────────────────────────────────────────────────────


def build_intent_chain(
    model_name: str,
    api_key: str = "",
    timeout_sec: float = 5.0,
):
    """
    Build and return a LangChain chain for intent classification.

    Parameters
    ----------
    model_name :
        OpenAI-compatible model identifier (e.g. "gpt-3.5-turbo").
    api_key :
        API key. If empty, falls back to OPENAI_API_KEY env var.
    timeout_sec :
        Per-request timeout passed to the LLM client.

    Returns
    -------
    A callable chain: chain.invoke({"text": ..., "context": ...,
                                    "valid_classes": ...}) → str
    """
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "LangChain intent chain requires an API key. "
            "Set the 'intent.langchain_api_key' ROS2 parameter "
            "or the OPENAI_API_KEY environment variable."
        )

    # Late imports — langchain not required at module load time
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except ImportError:
        from langchain.chat_models import ChatOpenAI  # type: ignore

    from langchain.prompts import ChatPromptTemplate  # type: ignore
    from langchain.schema.output_parser import StrOutputParser  # type: ignore

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=key,
        temperature=0,
        request_timeout=timeout_sec,
        max_tokens=32,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", _HUMAN_TEMPLATE),
        ]
    )

    return prompt | llm | StrOutputParser()


def classify_with_chain(
    chain,
    text: str,
    context: str,
    valid_classes: set,
) -> tuple[str, float]:
    """
    Invoke chain and parse the structured response.

    Raises ValueError on unparseable output; raises on LLM errors.
    """
    raw = chain.invoke(
        {
            "text": text,
            "context": context,
            "valid_classes": ", ".join(sorted(valid_classes)),
        }
    )
    return _parse_response(str(raw), valid_classes)
