"""
bonbon_llm.prompts.response_templates
======================================
Static fallback response templates used when:
  - Ollama is unavailable (LLM_ERROR)
  - Response confidence is too low (LOW_CONF)
  - Safety layer blocked the response (SAFETY_BLOCK)
  - Hallucination guard flagged the response (HALLUCINATION)
  - Unknown / unrecognised request (UNKNOWN)

Templates are keyed by situation.  Each has short and long variants
so the TTS length budget is respected.

All templates end with a question mark or a redirect to human staff
so the robot never leaves the customer without a next step.
"""

from __future__ import annotations

# ── Template registry ─────────────────────────────────────────────────────────


class FallbackTemplate:
    __slots__ = ("short", "long", "key")

    def __init__(self, key: str, short: str, long: str) -> None:
        self.key = key
        self.short = short
        self.long = long

    def get(self, prefer_short: bool = True) -> str:
        return self.short if prefer_short else self.long


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES: dict[str, FallbackTemplate] = {}


def _reg(key: str, short: str, long: str) -> None:
    TEMPLATES[key] = FallbackTemplate(key, short, long)


_reg(
    "llm_error",
    "Sorry, I'm having a moment. Could you repeat that?",
    "I'm sorry, I'm experiencing a technical issue right now. "
    "Please try again in a moment, or ask a member of staff for help.",
)

_reg(
    "low_confidence",
    "I'm not quite sure I understood. Could you say that again?",
    "I'm not confident I understood your request correctly. "
    "Could you please rephrase it or speak a little more clearly?",
)

_reg(
    "safety_block",
    "I can't do that right now for safety reasons.",
    "I'm sorry, that action isn't available right now due to the current safety state. "
    "Please speak to a member of staff if you need immediate assistance.",
)

_reg(
    "hallucination",
    "I'm not sure about that — let me get a staff member to help.",
    "I don't have reliable information about that right now. "
    "I'd rather get you accurate help from a staff member than guess.",
)

_reg(
    "unknown_request",
    "I didn't catch that. What would you like?",
    "I'm not sure what you'd like. Could you tell me again? "
    "I can take orders, answer menu questions, or help you navigate the café.",
)

_reg(
    "navigation_denied",
    "I can't navigate right now. Please ask a staff member.",
    "Navigation isn't available at the moment — my safety system requires a staff check first. "
    "A team member will be with you shortly.",
)

_reg(
    "actuation_denied",
    "I can't serve items right now. Please ask a staff member.",
    "Serving is paused at the moment due to the safety state. "
    "A staff member will help you right away.",
)

_reg(
    "silent",
    "I'm here if you need anything!",
    "I'm here and listening. Feel free to ask me anything about our menu or the café.",
)

_reg(
    "timeout",
    "I'm still thinking — just a moment!",
    "I'm processing your request — thank you for your patience, I'll be right with you.",
)

_reg(
    "ambiguous",
    "Could you be a little more specific? What would you like?",
    "I want to make sure I help you correctly. "
    "Could you tell me a bit more about what you'd like?",
)

_reg(
    "out_of_scope",
    "I can't help with that, but I can take orders and answer café questions.",
    "That's outside what I'm able to help with as a café robot. "
    "I'm best at taking orders, explaining the menu, and navigating the café. "
    "Is there anything like that I can help you with?",
)

_reg(
    "emergency",
    "Please speak to staff immediately. Help is on the way.",
    "This sounds urgent. Please speak to a staff member right away. "
    "If this is a medical emergency, please call 995.",
)

_reg(
    "greeting",
    "Hello! Welcome to the café. What can I get you today?",
    "Hello! I'm BonBon, your robot assistant. "
    "I can take your order, answer menu questions, or help you find a table. "
    "What can I do for you today?",
)


# ── Selector ──────────────────────────────────────────────────────────────────


def get_fallback(
    situation: str,
    prefer_short: bool = True,
    name: str = "BonBon",
) -> str:
    """
    Return the fallback string for ``situation``.

    Falls back to ``unknown_request`` if ``situation`` is not registered.
    Replaces ``{name}`` placeholder if present.
    """
    tmpl = TEMPLATES.get(situation, TEMPLATES["unknown_request"])
    text = tmpl.get(prefer_short)
    return text.replace("{name}", name)


def get_all_keys() -> list[str]:
    return list(TEMPLATES.keys())
