"""
bonbon_perception_ai.langchain_tools.scene_describer
=====================================================
Optional LangChain chain that generates richer natural-language scene
descriptions for use in logs, dashboards, or TTS output.

Falls back to the rule-based description from SceneAnalyzer when LangChain
is unavailable or disabled.

API key: same contract as intent_chain — never hardcoded.
"""

from __future__ import annotations

import os

from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an assistant for a service robot. "
    "Given a structured scene snapshot, write one concise sentence (≤ 25 words) "
    "describing what is happening. "
    "Be factual and direct. Do not start with 'The robot'."
)

_HUMAN_TEMPLATE = (
    "Persons: {person_count} | Nearest: {proximity} | "
    "Objects: {objects} | Activity: {activity} | "
    "Stale sensors: {stale}"
)


def build_scene_chain(
    model_name: str = "gpt-3.5-turbo",
    api_key: str = "",
    timeout_sec: float = 3.0,
):
    """Build the scene-description chain (lazy import)."""
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Scene describer requires an API key via 'intent.langchain_api_key' "
            "or OPENAI_API_KEY env var."
        )

    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except ImportError:
        from langchain.chat_models import ChatOpenAI  # type: ignore

    from langchain.prompts import ChatPromptTemplate  # type: ignore
    from langchain.schema.output_parser import StrOutputParser  # type: ignore

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=key,
        temperature=0.3,
        request_timeout=timeout_sec,
        max_tokens=60,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", _HUMAN_TEMPLATE),
        ]
    )
    return prompt | llm | StrOutputParser()


def describe_scene(chain, snap: SceneSnapshot) -> str:
    """
    Invoke chain and return a natural-language sentence.

    Falls back to snap.description on any error.
    """
    import math

    prox = f"{snap.human_proximity_m:.1f}m" if snap.human_proximity_m != math.inf else "none"
    try:
        return chain.invoke(
            {
                "person_count": len(snap.present_person_ids),
                "proximity": prox,
                "objects": ", ".join(snap.present_object_classes) or "none",
                "activity": snap.activity_label,
                "stale": ", ".join(snap.stale_modalities) or "none",
            }
        )
    except Exception:
        return snap.description
